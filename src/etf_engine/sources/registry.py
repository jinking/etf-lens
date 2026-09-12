from dataclasses import dataclass

from etf_engine.sources.akshare.calendar import AkshareTradingCalendarSource
from etf_engine.sources.akshare.history import AkshareETFHistorySource
from etf_engine.sources.akshare.holdings import AkshareETFHoldingSource
from etf_engine.sources.akshare.index_data import (
    AkshareETFBenchmarkSource,
    AkshareIndexCatalogSource,
    AkshareIndexConstituentSource,
    AkshareIndexQuoteSource,
)
from etf_engine.sources.akshare.industry import AkshareStockIndustrySource
from etf_engine.sources.akshare.nav import AkshareETFNavHistorySource, AkshareETFNavSource
from etf_engine.sources.akshare.quotes import AkshareETFQuoteSource
from etf_engine.sources.master import UnifiedETFMasterSource
from etf_engine.sources.sse.shares import SSEETFShareSource
from etf_engine.sources.szse.shares import SZSEETFShareSource


@dataclass(frozen=True, slots=True)
class SourceRegistry:
    """V1 默认能力注册表。

    后续接入 HiThink / Wind / Choice 时，不修改 Service 层；
    只扩展注册表与 capability policy。

    Registry 是业务层（``jobs/``）拿到适配器的唯一入口：job 不允许直接
    import 某个具体适配器，否则"换数据源不改业务代码"这条架构目标立刻失效。
    """

    master_source = UnifiedETFMasterSource
    quote_source = AkshareETFQuoteSource
    history_source = AkshareETFHistorySource
    nav_source = AkshareETFNavSource
    nav_history_source = AkshareETFNavHistorySource
    holding_source = AkshareETFHoldingSource
    holding_source = AkshareETFHoldingSource
    calendar_source = AkshareTradingCalendarSource
    industry_source = AkshareStockIndustrySource
    index_catalog_source = AkshareIndexCatalogSource
    index_constituent_source = AkshareIndexConstituentSource
    index_quote_source = AkshareIndexQuoteSource
    index_benchmark_source = AkshareETFBenchmarkSource
    share_sources = (SSEETFShareSource, SZSEETFShareSource)


registry = SourceRegistry()
