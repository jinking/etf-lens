from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel

from .enums import Exchange, QualityStatus


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


class IndexQuote(BaseModel):
    index_id: str
    trade_date: date
    open: Decimal | None = None
    high: Decimal | None = None
    low: Decimal | None = None
    close: Decimal | None = None
    currency: str | None = "CNY"
    source_meta: SourceMeta


class FundProfile(BaseModel):
    """基金披露的档案事实（东方财富基金概况页）。

    这些字段是基金公司披露的静态信息，与行情无关；用于补齐
    ``core.etf_master`` 里费率、成立日期、管理人等长期缺失的字段。
    """

    security_id: str
    fund_name: str | None = None
    short_name: str | None = None
    fund_type: str | None = None
    established_date: date | None = None
    manager_name: str | None = None
    custodian_name: str | None = None
    management_fee_pct: Decimal | None = None
    custodian_fee_pct: Decimal | None = None
    tracking_target: str | None = None
    benchmark: str | None = None
    source_meta: SourceMeta


class MarketTurnover(BaseModel):
    """交易所每日概况（口径：该交易所的股票，含各板块，不含基金债券）。

    ``turnover_amount`` 一律为**元**；上游给亿元时由适配器换算。
    深交所每日统计不披露换手率，保持 NULL，不用"成交额 ÷ 流通市值"顶替。
    """

    trade_date: date
    exchange: Exchange
    turnover_amount: Decimal | None = None
    turnover_rate_pct: Decimal | None = None
    float_market_cap: Decimal | None = None
    total_market_cap: Decimal | None = None
    listing_count: Decimal | None = None
    source_meta: SourceMeta


class MarginBalance(BaseModel):
    """融资融券余额（按市场分列，合计由 mart 派生）。"""

    trade_date: date
    exchange: Exchange
    financing_balance: Decimal | None = None
    financing_buy_amount: Decimal | None = None
    securities_lending_balance: Decimal | None = None
    margin_balance: Decimal | None = None
    source_meta: SourceMeta


class MarketValuation(BaseModel):
    """估值与历史分位。

    分位由上游直接给出（上游自带全历史/近十年分位），属于事实；
    本系统不做二次推导，也不把不同来源的分位混用，口径写在 ``metric_basis``。
    """

    index_id: str
    trade_date: date
    index_close: Decimal | None = None
    pe_ttm_median: Decimal | None = None
    pe_ttm_mean: Decimal | None = None
    pe_lyr_median: Decimal | None = None
    pe_lyr_mean: Decimal | None = None
    quantile_ttm_median_all_history: Decimal | None = None
    quantile_ttm_median_10y: Decimal | None = None
    quantile_lyr_median_all_history: Decimal | None = None
    quantile_lyr_median_10y: Decimal | None = None
    metric_basis: str | None = None
    source_meta: SourceMeta


class MarketActivity(BaseModel):
    """全市场涨跌家数与活跃度（情绪温度）。"""

    trade_date: date
    rising_count: Decimal | None = None
    falling_count: Decimal | None = None
    flat_count: Decimal | None = None
    suspended_count: Decimal | None = None
    limit_up_count: Decimal | None = None
    limit_down_count: Decimal | None = None
    real_limit_up_count: Decimal | None = None
    real_limit_down_count: Decimal | None = None
    activity_pct: Decimal | None = None
    statistic_at: datetime | None = None
    source_meta: SourceMeta


class IndexValuation(BaseModel):
    """单条指数的市盈率序列（月末观测，上游按加权/等权两种口径提供）。

    与 :class:`MarketValuation`（全 A 口径、上游自带分位）是两件事，不混用。
    """

    index_id: str
    trade_date: date
    pe_static: Decimal | None = None
    pe_ttm: Decimal | None = None
    pe_static_median: Decimal | None = None
    pe_ttm_median: Decimal | None = None
    pe_static_equal_weight: Decimal | None = None
    pe_ttm_equal_weight: Decimal | None = None
    metric_basis: str | None = None
    source_meta: SourceMeta


class FundIssuance(BaseModel):
    """新发基金事实（一行一只基金）。

    ``raised_shares`` 是募集份额（**亿元**），上游部分基金不披露 → NULL。
    ``established_date`` 是成立日期：月度规模按它聚合，而不是按募集起始日。
    """

    fund_code: str
    fund_name: str | None = None
    company: str | None = None
    fund_type: str | None = None
    subscription_period: str | None = None
    raised_shares: Decimal | None = None
    established_date: date | None = None
    manager: str | None = None
    source_meta: SourceMeta
