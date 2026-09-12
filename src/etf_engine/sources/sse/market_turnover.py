"""上交所每日概况：成交额 / 换手率 / 市值。

来源是交易所官方发布的"市场成交概况"页（AKShare 的 ``stock_sse_deal_daily``）。
上游单位是**亿元**，本适配器统一换算成**元**再落库，原始表照原样写入 raw。
"""

from datetime import date, datetime
from decimal import Decimal

import akshare as ak
import pandas as pd

from etf_engine.domain.enums import Exchange, QualityStatus
from etf_engine.domain.models import MarketTurnover, SourceMeta
from etf_engine.domain.quality import DataQualityIssue, warn
from etf_engine.sources.base import MarketTurnoverSource

#: 上游金额字段的单位换算：亿元 → 元。
_YI = Decimal(100_000_000)


def _decimal(value) -> Decimal | None:
    if value is None or pd.isna(value):
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _items(frame: pd.DataFrame) -> dict[str, pd.Series]:
    """把"单日情况"为行的宽表转成 ``{指标名: 该行}``。"""
    if "单日情况" not in frame.columns:
        raise RuntimeError("上交所每日概况缺少 单日情况 列")
    return {str(row["单日情况"]).strip(): row for _, row in frame.iterrows()}


def parse_sse_deal_daily(
    frame: pd.DataFrame,
    *,
    trade_date: date,
    fetched_at: datetime,
) -> tuple[MarketTurnover | None, list[DataQualityIssue]]:
    """解析上交所每日概况。

    取"股票"列（= 主板A + 主板B + 科创板），这与本方案声明的
    "沪深两市股票"口径一致；基金、债券的成交额不计入。
    """
    issues: list[DataQualityIssue] = []
    if frame is None or frame.empty:
        return None, [warn("market_turnover_empty", f"上交所每日概况空结果 {trade_date}")]

    items = _items(frame)
    if "股票" not in frame.columns:
        return None, [warn("market_turnover_schema", "上交所每日概况缺少 股票 列")]

    def pick(name: str, *, scale: Decimal = Decimal(1)) -> Decimal | None:
        row = items.get(name)
        if row is None:
            issues.append(warn("market_turnover_missing_field", f"上交所缺少 {name} 行"))
            return None
        value = _decimal(row["股票"])
        return None if value is None else value * scale

    turnover_amount = pick("成交金额", scale=_YI)
    if turnover_amount is None:
        return None, [warn("market_turnover_missing_field", f"上交所 {trade_date} 没有成交金额")]

    return (
        MarketTurnover(
            trade_date=trade_date,
            exchange=Exchange.SSE,
            turnover_amount=turnover_amount,
            #: 交易所口径换手率（%），不是本系统推导的。
            turnover_rate_pct=pick("换手率"),
            float_market_cap=pick("流通市值", scale=_YI),
            total_market_cap=pick("市价总值", scale=_YI),
            listing_count=pick("挂牌数"),
            source_meta=SourceMeta(
                source="sse",
                upstream_source="sse",
                fetched_at=fetched_at,
                quality_status=QualityStatus.PASS,
            ),
        ),
        issues,
    )


class SSEMarketTurnoverSource(MarketTurnoverSource):
    exchange = Exchange.SSE
    source_name = "sse"

    def fetch_turnover(self, trade_date: date) -> MarketTurnover | None:
        turnover, _ = self.fetch_turnover_with_issues(trade_date)
        return turnover[0] if turnover else None

    def fetch_turnover_with_issues(
        self, trade_date: date
    ) -> tuple[list[MarketTurnover], list[DataQualityIssue]]:
        fetched_at = datetime.now().astimezone()
        frame = ak.stock_sse_deal_daily(date=trade_date.strftime("%Y%m%d"))
        turnover, issues = parse_sse_deal_daily(frame, trade_date=trade_date, fetched_at=fetched_at)
        return ([turnover] if turnover is not None else []), issues
