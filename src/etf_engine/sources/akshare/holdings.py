"""东方财富 ETF 披露持仓适配器（上游事实来源：eastmoney）。

历史实现有三个数据完整性问题，这里一并修掉：

1. 把上游返回的 5 位港股代码 ``01801`` 补零成 ``001801`` 再按首位推断交易所，
   结果信达生物被写成深市 A 股 ``001801.SZ``，与真实存在的深市代码静默合并；
2. 用 ``df["季度"].iloc[0]`` 取季度，实测该表是升序，取到的是**最旧**的季度；
3. 把 ``disclosure_date`` 直接填成 ``report_date``，等于凭空造出一个披露日。
   披露日在接口里并不存在，保持 NULL（未知 ≠ 有值）。

另外，历史上任意一行代码解析失败都会让整只 ETF 的 10 条持仓全部丢失，
现在改为逐行跳过并把问题交给 ``ops.quality_issue``。
"""

import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

import akshare as ak
import pandas as pd

from etf_engine.domain.enums import QualityStatus
from etf_engine.domain.identifiers import SecurityId
from etf_engine.domain.models import ETFHolding, SourceMeta
from etf_engine.domain.quality import DataQualityIssue, warn
from etf_engine.sources.base import ETFHoldingSource

#: 单只 ETF 保留的披露持仓条数。
TOP_HOLDINGS = 10

_QUARTER_PATTERN = re.compile(r"(\d{4})年(\d)季度")
_QUARTER_END = {1: (3, 31), 2: (6, 30), 3: (9, 30), 4: (12, 31)}


@dataclass(frozen=True, slots=True)
class HoldingParseResult:
    holdings: list[ETFHolding]
    issues: list[DataQualityIssue]
    report_date: date | None


def _decimal(value) -> Decimal | None:
    if value is None or pd.isna(value):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def parse_quarter_to_date(quarter_str: str) -> date:
    """将 ``2026年2季度股票投资明细`` 转换为报告期 ``2026-06-30``。"""
    match = _QUARTER_PATTERN.search(str(quarter_str))
    if not match:
        raise ValueError(f"Cannot parse report quarter: {quarter_str!r}")
    year, quarter = int(match.group(1)), int(match.group(2))
    month_day = _QUARTER_END.get(quarter)
    if month_day is None:
        raise ValueError(f"Unsupported quarter: {quarter_str!r}")
    return date(year, month_day[0], month_day[1])


def _normalize_stock_code(value) -> str:
    if value is None or pd.isna(value):
        return ""
    raw = str(value).strip()
    if raw.endswith(".0"):
        raw = raw[:-2]
    return raw


def parse_holdings_frame(
    frame: pd.DataFrame,
    *,
    security_id: str,
    fetched_at: datetime,
) -> HoldingParseResult:
    """解析最新一期的前十大披露持仓。"""
    issues: list[DataQualityIssue] = []

    for column in ("股票代码", "季度"):
        if column not in frame.columns:
            raise RuntimeError(f"ETF holding frame is missing the {column} column.")

    dated_rows: list[tuple[date, int]] = []
    for index, row in frame.iterrows():
        try:
            dated_rows.append((parse_quarter_to_date(row["季度"]), index))
        except ValueError:
            issues.append(warn("holding_quarter_unparsed", f"季度={row['季度']!r}"))

    if not dated_rows:
        return HoldingParseResult([], issues, None)

    report_date = max(item[0] for item in dated_rows)
    latest_rows = frame.loc[[index for day, index in dated_rows if day == report_date]].copy()
    latest_rows["_weight"] = pd.to_numeric(latest_rows["占净值比例"], errors="coerce")
    latest_rows = latest_rows.sort_values("_weight", ascending=False, na_position="last")

    holdings: list[ETFHolding] = []
    for _, row in latest_rows.head(TOP_HOLDINGS).iterrows():
        raw_code = _normalize_stock_code(row.get("股票代码"))
        if not raw_code:
            issues.append(
                warn(
                    "holding_stock_code_missing",
                    f"{security_id} 股票名称={row.get('股票名称')!r}",
                )
            )
            continue
        try:
            stock_id = SecurityId.parse(raw_code).value
        except ValueError:
            issues.append(
                warn(
                    "holding_stock_code_unresolved",
                    f"{security_id} 股票代码={raw_code!r} 股票名称={row.get('股票名称')!r}",
                )
            )
            continue

        holdings.append(
            ETFHolding(
                etf_id=security_id,
                report_date=report_date,
                disclosure_date=None,
                stock_id=stock_id,
                stock_name=str(row.get("股票名称", "")).strip() or None,
                weight_pct=_decimal(row.get("占净值比例")),
                shares=_decimal(row.get("持股数")),
                market_value=_decimal(row.get("持仓市值")),
                source_meta=SourceMeta(
                    source="akshare",
                    upstream_source="eastmoney",
                    fetched_at=fetched_at,
                    quality_status=QualityStatus.PASS,
                ),
            )
        )

    return HoldingParseResult(holdings, issues, report_date)


class AkshareETFHoldingSource(ETFHoldingSource):
    """东方财富 ETF 披露持仓。"""

    def _fetch_frame(self, ticker: str, reference: date) -> pd.DataFrame | None:
        for year in (reference.year, reference.year - 1, reference.year - 2):
            try:
                frame = ak.fund_portfolio_hold_em(symbol=ticker, date=str(year))
            except Exception:
                continue
            if frame is not None and not frame.empty:
                return frame
        return None

    def fetch_holdings(self, security_id: str, report_date: date | None = None) -> list[ETFHolding]:
        return self._parse(security_id, report_date).holdings

    def fetch_holdings_with_issues(
        self, security_id: str, report_date: date | None = None
    ) -> tuple[list[ETFHolding], list[DataQualityIssue]]:
        result = self._parse(security_id, report_date)
        return result.holdings, result.issues

    def _parse(self, security_id: str, report_date: date | None) -> HoldingParseResult:
        sid = SecurityId.parse(security_id)
        fetched_at = datetime.now().astimezone()
        frame = self._fetch_frame(sid.ticker, report_date or fetched_at.date())
        if frame is None:
            return HoldingParseResult([], [], None)
        return parse_holdings_frame(frame, security_id=sid.value, fetched_at=fetched_at)
