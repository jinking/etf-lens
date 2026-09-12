from datetime import date

from pydantic import BaseModel, Field


class HoldingItem(BaseModel):
    stock_id: str
    stock_name: str | None = None
    weight_pct: float | None = None


class TrackingIndex(BaseModel):
    id: str | None = None
    name: str | None = None
    source: str | None = None


class CoreMetricsQuality(BaseModel):
    status: str = "PASS"
    reasons: dict[str, str] = Field(default_factory=dict)
    source_asof_dates: dict[str, date | None] = Field(default_factory=dict)


class ETFCoreMetrics(BaseModel):
    security_id: str
    asof_date: date
    tracking_index: TrackingIndex
    top10: list[HoldingItem] = Field(default_factory=list)
    top10_concentration: float | None = None
    holdings_asof_date: date | None = None
    holdings_type: str | None = None
    premium_discount_pct: float | None = None
    turnover_amount: float | None = None
    avg_turnover_amount_20d: float | None = None
    bid1: float | None = None
    ask1: float | None = None
    bid_ask_spread: float | None = None
    bid_ask_spread_pct: float | None = None
    reported_aum: float | None = None
    reported_aum_date: date | None = None
    estimated_aum: float | None = None
    estimated_aum_date: date | None = None
    estimated_aum_is_estimated: bool | None = None
    share_change_20d: float | None = None
    share_change_pct_20d: float | None = None
    estimated_net_subscription_20d: float | None = None
    estimated_net_subscription_is_estimated: bool | None = None
    estimated_net_subscription_calculation_version: str | None = None
    market_return_20d: float | None = None
    market_return_60d: float | None = None
    max_drawdown_60d: float | None = None
    tracking_error_60d: float | None = None
    quality: CoreMetricsQuality
