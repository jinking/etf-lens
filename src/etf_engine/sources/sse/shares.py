"""上交所 ETF 份额适配器。

上游事实来源：上交所官网 ``query.sse.com.cn`` 的 ETF 规模接口。

历史实现有两个坑，这里全部绕开：

1. AKShare 的 ``fund_etf_scale_sse`` 默认参数被硬编码为 ``"20250115"``，
   不带日期调用只会拿回 2025-01-15 那一天的数据；因此本适配器永远显式传
   ``STAT_DATE``，并从接口返回的 ``STAT_DATE`` 读取真实统计日期。
2. 接口没有净值字段，``nav`` 保持 NULL，不用其它来源的值顶替（净值由
   :mod:`etf_engine.sources.akshare.nav` 单独采集，并在份额入库时单独标注
   ``nav_source``）。
"""

from datetime import date, datetime
from decimal import Decimal, InvalidOperation

import requests

from etf_engine.domain.calendar import MarketCalendar
from etf_engine.domain.enums import QualityStatus
from etf_engine.domain.identifiers import SecurityId
from etf_engine.domain.models import ETFShare, SourceMeta
from etf_engine.domain.quality import DataQualityIssue, error, warn
from etf_engine.sources.base import ETFShareSource

SSE_SCALE_URL = "https://query.sse.com.cn/commonQuery.do"
SSE_SCALE_SQL_ID = "COMMON_SSE_ZQPZ_ETFZL_XXPL_ETFGM_SEARCH_L"

#: 接口按"万份"披露份额。
SSE_SHARE_UNIT = Decimal(10000)

#: 目标交易日无数据时，最多向前回看多少个交易日。
DEFAULT_LOOKBACK_TRADING_DAYS = 5


def _fetch_sse_scale_rows(stat_date: str, *, timeout: float = 20.0) -> list[dict]:
    """按 ``YYYYMMDD`` 拉取上交所 ETF 规模明细。"""
    params = {
        "isPagination": "true",
        "pageHelp.pageSize": "10000",
        "pageHelp.pageNo": "1",
        "pageHelp.beginPage": "1",
        "pageHelp.cacheSize": "1",
        "pageHelp.endPage": "1",
        "sqlId": SSE_SCALE_SQL_ID,
        "STAT_DATE": f"{stat_date[:4]}-{stat_date[4:6]}-{stat_date[6:]}",
    }
    headers = {"Referer": "https://www.sse.com.cn/", "User-Agent": "Mozilla/5.0"}
    response = requests.get(SSE_SCALE_URL, params=params, headers=headers, timeout=timeout)
    response.raise_for_status()
    return response.json().get("result") or []


def _decimal(value) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, ValueError, AttributeError):
        return None


def parse_sse_rows(
    rows: list[dict],
    *,
    fetched_at: datetime,
    requested_asof: date | None = None,
) -> tuple[list[ETFShare], list[DataQualityIssue]]:
    shares: list[ETFShare] = []
    issues: list[DataQualityIssue] = []

    for row in rows:
        raw_code = str(row.get("SEC_CODE", "")).strip()
        try:
            security_id = SecurityId.parse(f"{raw_code}.SH").value
        except ValueError:
            issues.append(warn("share_code_unresolved", f"SEC_CODE={raw_code!r}"))
            continue

        raw_date = str(row.get("STAT_DATE", "")).strip()
        try:
            trade_date = date.fromisoformat(raw_date)
        except ValueError:
            issues.append(warn("share_stat_date_invalid", f"{security_id} STAT_DATE={raw_date!r}"))
            continue

        shares_value = _decimal(row.get("TOT_VOL"))
        if shares_value is None:
            issues.append(
                warn(
                    "share_volume_unresolved",
                    f"{security_id} TOT_VOL={row.get('TOT_VOL')!r}",
                )
            )
            continue

        if requested_asof is not None and trade_date < requested_asof:
            issues.append(
                warn(
                    "share_stat_date_behind_request",
                    f"{security_id} STAT_DATE={trade_date.isoformat()} "
                    f"< asof={requested_asof.isoformat()}",
                )
            )

        shares.append(
            ETFShare(
                security_id=security_id,
                trade_date=trade_date,
                fund_name=str(row.get("SEC_NAME", "")).strip() or None,
                shares=shares_value * SSE_SHARE_UNIT,
                nav=None,
                source_meta=SourceMeta(
                    source="sse",
                    upstream_source="sse",
                    fetched_at=fetched_at,
                    quality_status=QualityStatus.PASS,
                ),
            )
        )

    return shares, issues


class SSEETFShareSource(ETFShareSource):
    """上交所 ETF 份额。

    ``snapshot_date_is_derived`` 为 ``False``：交接口自带 ``STAT_DATE``，
    入库日期来自上游而不是本地推断。
    """

    snapshot_date_is_derived = False
    source_name = "sse"
    supports_history_backfill = True

    def __init__(
        self,
        calendar: MarketCalendar | None = None,
        lookback: int = DEFAULT_LOOKBACK_TRADING_DAYS,
    ):
        self.calendar = calendar
        self.lookback = lookback

    def _candidate_dates(self, trade_date: date | None) -> list[date]:
        if trade_date is not None:
            if self.calendar is None:
                return [trade_date]
            candidates = self.calendar.trading_days_back(trade_date, self.lookback)
            if not candidates:
                candidates = [trade_date]
            if trade_date not in candidates:
                # 显式指定的日期不是交易日时，仍然先试一次再回看。
                candidates.insert(0, trade_date)
            return candidates

        if self.calendar is None:
            raise ValueError(
                "SSE 份额采集需要交易日历或显式 trade_date："
                "上交所规模接口的默认日期是硬编码的 20250115，不许在不指定日期的情况下调用。"
            )
        now = datetime.now().astimezone()
        return self.calendar.trading_days_back(
            self.calendar.latest_closed_trading_day(now), self.lookback
        )

    def fetch_shares(self, trade_date: date | None = None) -> list[ETFShare]:
        shares, _ = self.fetch_shares_with_issues(trade_date=trade_date)
        return shares

    def fetch_shares_with_issues(
        self, trade_date: date | None = None
    ) -> tuple[list[ETFShare], list[DataQualityIssue]]:
        fetched_at = datetime.now().astimezone()
        for candidate in self._candidate_dates(trade_date):
            rows = _fetch_sse_scale_rows(candidate.strftime("%Y%m%d"))
            if not rows:
                continue
            return parse_sse_rows(rows, fetched_at=fetched_at, requested_asof=trade_date)
        return [], []

    def fetch_shares_history(
        self, asof: date, trading_days: int
    ) -> tuple[list[ETFShare], list[DataQualityIssue]]:
        """按交易日逐日回补上交所份额（每个日期只请求一次，缺数据即留空）。"""
        if self.calendar is None:
            raise ValueError("份额历史回补需要交易日历。")

        fetched_at = datetime.now().astimezone()
        shares: list[ETFShare] = []
        issues: list[DataQualityIssue] = []

        for candidate in self.calendar.trading_days_back(asof, trading_days):
            try:
                rows = _fetch_sse_scale_rows(candidate.strftime("%Y%m%d"))
            except Exception as exc:
                # 单日接口抖动不能让整个回补区间失败，缺口如实记录。
                issues.append(
                    error("share_history_fetch_failed", f"STAT_DATE={candidate.isoformat()}: {exc}")
                )
                continue
            if not rows:
                # 上交所规模接口并非每个交易日都有披露，缺口如实记录，不插值。
                issues.append(
                    warn("share_history_missing_date", f"STAT_DATE={candidate.isoformat()}")
                )
                continue
            day_shares, day_issues = parse_sse_rows(rows, fetched_at=fetched_at)
            shares.extend(day_shares)
            issues.extend(day_issues)

        return shares, issues
