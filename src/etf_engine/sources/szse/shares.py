"""深交所 ETF 份额适配器。

上游事实来源：深交所基金列表接口（xlsx 快照）。

该接口是"当前快照"，不含统计日期字段，因此入库日期必须由交易日历解析
（``snapshot_date_is_derived = True``），绝不使用 ``datetime.now().date()``。
历史实现正是用运行日当交易日，把一条周六（2026-09-12）的数据写进了库。

AKShare 的 ``fund_etf_scale_szse`` 在当前版本会抛 ``TypeError``（把 bytes
直接交给 ``read_excel``），因此这里直接下载 xlsx。
"""

import io
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

import pandas as pd
import requests

from etf_engine.domain.calendar import MarketCalendar
from etf_engine.domain.enums import QualityStatus
from etf_engine.domain.identifiers import SecurityId
from etf_engine.domain.models import ETFShare, SourceMeta
from etf_engine.domain.quality import DataQualityIssue, warn
from etf_engine.sources.base import ETFShareSource

SZSE_FUND_LIST_URL = "https://fund.szse.cn/api/report/ShowReport"
SZSE_FUND_LIST_PARAMS = {
    "SHOWTYPE": "xlsx",
    "CATALOGID": "1000_lf",
    "TABKEY": "tab1",
}


def fetch_szse_fund_frame(*, timeout: float = 20.0) -> pd.DataFrame:
    """下载深交所基金列表 xlsx 快照。"""
    headers = {
        "Referer": "https://fund.szse.cn/marketdata/fundslist/index.html",
        "User-Agent": "Mozilla/5.0",
    }
    response = requests.get(
        SZSE_FUND_LIST_URL, params=SZSE_FUND_LIST_PARAMS, headers=headers, timeout=timeout
    )
    response.raise_for_status()
    return pd.read_excel(io.BytesIO(response.content), engine="openpyxl", dtype={"基金代码": str})


def _decimal(value) -> Decimal | None:
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        return None
    try:
        return Decimal(str(value).replace(",", "").strip())
    except (InvalidOperation, ValueError, AttributeError):
        return None


def parse_szse_frame(
    frame: pd.DataFrame,
    *,
    asof: date,
    fetched_at: datetime,
) -> tuple[list[ETFShare], list[DataQualityIssue]]:
    """把深交所基金列表解析成标准 ETFShare 事实。

    ``asof`` 必须来自交易日历：该快照没有自带日期字段。
    """
    shares: list[ETFShare] = []
    issues: list[DataQualityIssue] = []

    if "基金代码" not in frame.columns:
        raise RuntimeError("SZSE fund list is missing the 基金代码 column.")

    for _, row in frame.iterrows():
        raw_code = str(row.get("基金代码", "")).strip()
        try:
            security_id = SecurityId.parse(raw_code).value
        except ValueError:
            issues.append(warn("share_code_unresolved", f"基金代码={raw_code!r}"))
            continue

        shares_value = _decimal(row.get("当前规模(份)", row.get("基金份额")))
        if shares_value is None:
            issues.append(
                warn(
                    "share_volume_unresolved",
                    f"{security_id} 当前规模(份)={row.get('当前规模(份)')!r}",
                )
            )
            continue

        shares.append(
            ETFShare(
                security_id=security_id,
                trade_date=asof,
                fund_name=str(row.get("基金简称", "")).strip() or None,
                shares=shares_value,
                nav=_decimal(row.get("净值")),
                nav_source="szse" if _decimal(row.get("净值")) is not None else None,
                source_meta=SourceMeta(
                    source="szse",
                    upstream_source="szse",
                    fetched_at=fetched_at,
                    quality_status=QualityStatus.PASS,
                ),
            )
        )

    return shares, issues


class SZSEETFShareSource(ETFShareSource):
    """深交所 ETF 当前份额快照。"""

    snapshot_date_is_derived = True
    source_name = "szse"

    def __init__(self, calendar: MarketCalendar | None = None):
        self.calendar = calendar

    def _asof(self, trade_date: date | None) -> date:
        if trade_date is not None:
            return trade_date
        if self.calendar is None:
            raise ValueError(
                "SZSE 份额快照没有自带日期，必须提供交易日历或显式 trade_date，"
                "不允许用运行日（可能是周末/节假日）当交易日。"
            )
        return self.calendar.latest_closed_trading_day(datetime.now().astimezone())

    def fetch_shares(self, trade_date: date | None = None) -> list[ETFShare]:
        shares, _ = self.fetch_shares_with_issues(trade_date=trade_date)
        return shares

    def fetch_shares_with_issues(
        self, trade_date: date | None = None
    ) -> tuple[list[ETFShare], list[DataQualityIssue]]:
        asof = self._asof(trade_date)
        fetched_at = datetime.now().astimezone()
        frame = fetch_szse_fund_frame()
        return parse_szse_frame(frame, asof=asof, fetched_at=fetched_at)
