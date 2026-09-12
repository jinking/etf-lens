from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel

from .enums import QualityStatus


class SourceMeta(BaseModel):
    source: str
    upstream_source: str | None = None
    fetched_at: datetime
    quality_status: QualityStatus = QualityStatus.PASS
    ingestion_run_id: str | None = None


class ETFQuote(BaseModel):
    security_id: str
    trade_date: date
    name: str | None = None

    open: Decimal | None = None
    high: Decimal | None = None
    low: Decimal | None = None
    close: Decimal | None = None
    prev_close: Decimal | None = None

    change: Decimal | None = None
    change_pct: Decimal | None = None
    volume: Decimal | None = None
    turnover_amount: Decimal | None = None
    turnover_rate: Decimal | None = None
    amplitude: Decimal | None = None

    iopv: Decimal | None = None
    premium_discount_pct: Decimal | None = None
    premium_discount_pct_normalized: Decimal | None = None
    bid1: Decimal | None = None
    ask1: Decimal | None = None
    bid1_volume: Decimal | None = None
    ask1_volume: Decimal | None = None

    trading_flow_main: Decimal | None = None
    trading_flow_super_large: Decimal | None = None
    trading_flow_large: Decimal | None = None
    trading_flow_medium: Decimal | None = None
    trading_flow_small: Decimal | None = None

    source_meta: SourceMeta


class ETFShare(BaseModel):
    security_id: str
    trade_date: date
    fund_name: str | None = None
    shares: Decimal
    nav: Decimal | None = None
    #: nav 的独立来源。份额接口（SSE 规模接口）不提供净值时，净值可能来自
    #: 另一个数据源，必须单独记录，避免把跨源拼接结果伪装成单一来源事实。
    nav_source: str | None = None
    source_meta: SourceMeta


class ETFMaster(BaseModel):
    security_id: str
    ticker: str
    exchange: str
    fund_name: str | None = None
    short_name: str | None = None
    fund_type: str | None = None
    investment_type: str | None = None
    manager_name: str | None = None
    custodian_name: str | None = None
    established_date: date | None = None
    listed_date: date | None = None
    tracking_index_id: str | None = None
    tracking_index_name: str | None = None
    reported_aum: Decimal | None = None
    reported_aum_date: date | None = None
    asset_region: str | None = None
    base_currency: str | None = "CNY"
    tracking_index_currency: str | None = None
    is_cross_border: bool = False
    management_fee_pct: Decimal | None = None
    custodian_fee_pct: Decimal | None = None
    status: str = "ACTIVE"
    source_meta: SourceMeta


class ETFNav(BaseModel):
    security_id: str
    nav_date: date
    unit_nav: Decimal
    adjusted_nav: Decimal | None = None
    source_meta: SourceMeta


class ETFHolding(BaseModel):
    etf_id: str
    report_date: date
    disclosure_date: date | None = None
    stock_id: str
    stock_name: str | None = None
    weight_pct: Decimal | None = None
    shares: Decimal | None = None
    market_value: Decimal | None = None
    source_meta: SourceMeta


class IndexConstituent(BaseModel):
    index_id: str
    effective_date: date
    stock_id: str
    stock_name: str | None = None
    weight_pct: Decimal | None = None
    source_meta: SourceMeta


class StockIndustry(BaseModel):
    """个股行业分类事实。

    ``classification_standard`` 记录分类标准（如"中证行业分类标准"），
    不同标准不合并——行业不是唯一事实，口径必须可追溯。
    """

    stock_id: str
    stock_name: str | None = None
    industry_name: str
    industry_code: str | None = None
    classification_standard: str | None = None
    source_meta: SourceMeta


class IndexCatalogEntry(BaseModel):
    index_id: str
    index_name: str
    market_symbol: str | None = None
    source_meta: SourceMeta
