"""深交所每日统计：成交额 / 市值（不含换手率）。

上游单位是**元**，与上交所（亿元）不同；两边都在适配器里统一成元。
深交所本期不披露换手率，字段保持 NULL——不用"成交额 ÷ 流通市值"顶替，
那是一个不同的指标，真要展示得另起字段名。
"""

from datetime import date, datetime
from decimal import Decimal

import akshare as ak
import pandas as pd

from etf_engine.domain.enums import Exchange, QualityStatus
from etf_engine.domain.models import MarketTurnover, SourceMeta
from etf_engine.domain.quality import DataQualityIssue, warn
from etf_engine.sources.base import MarketTurnoverSource

#: 深交所"证券类别"里代表股票大类的行。
STOCK_CATEGORY = "股票"


def _decimal(value) -> Decimal | None:
    if value is None or pd.isna(value):
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def parse_szse_summary(
    frame: pd.DataFrame,
    *,
    trade_date: date,
    fetched_at: datetime,
) -> tuple[MarketTurnover | None, list[DataQualityIssue]]:
    if frame is None or frame.empty:
        return None, [warn("market_turnover_empty", f"深交所每日统计空结果 {trade_date}")]

    for column in ("证券类别", "成交金额"):
        if column not in frame.columns:
            return None, [warn("market_turnover_schema", f"深交所每日统计缺少 {column} 列")]

    matched = frame[frame["证券类别"].astype(str).str.strip() == STOCK_CATEGORY]
    if matched.empty:
        return None, [warn("market_turnover_missing_field", f"深交所 {trade_date} 没有股票大类行")]

    row = matched.iloc[0]
    turnover_amount = _decimal(row["成交金额"])
    if turnover_amount is None:
        return None, [
            warn("market_turnover_missing_field", f"深交所 {trade_date} 股票成交金额为 NULL")
        ]

    return (
        MarketTurnover(
            trade_date=trade_date,
            exchange=Exchange.SZSE,
            turnover_amount=turnover_amount,
            #: 深交所不披露换手率：NULL，不是 0。
            turnover_rate_pct=None,
            float_market_cap=_decimal(row.get("流通市值")),
            total_market_cap=_decimal(row.get("总市值")),
            listing_count=_decimal(row.get("数量")),
            source_meta=SourceMeta(
                source="szse",
                upstream_source="szse",
                fetched_at=fetched_at,
                quality_status=QualityStatus.PASS,
            ),
        ),
        [],
    )


class SZSEMarketTurnoverSource(MarketTurnoverSource):
    exchange = Exchange.SZSE
    source_name = "szse"

    def fetch_turnover(self, trade_date: date) -> MarketTurnover | None:
        turnover, _ = self.fetch_turnover_with_issues(trade_date)
        return turnover[0] if turnover else None

    def fetch_turnover_with_issues(
        self, trade_date: date
    ) -> tuple[list[MarketTurnover], list[DataQualityIssue]]:
        fetched_at = datetime.now().astimezone()
        frame = ak.stock_szse_summary(date=trade_date.strftime("%Y%m%d"))
        turnover, issues = parse_szse_summary(frame, trade_date=trade_date, fetched_at=fetched_at)
        return ([turnover] if turnover is not None else []), issues
