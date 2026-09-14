from dataclasses import dataclass

from etf_engine.sources.akshare.activity import AkshareMarketActivitySource
from etf_engine.sources.akshare.calendar import AkshareTradingCalendarSource
from etf_engine.sources.akshare.corporate_action import EastmoneyFundActionSource
from etf_engine.sources.akshare.fund_issuance import AkshareFundIssuanceSource
from etf_engine.sources.akshare.fund_profile import AkshareFundProfileSource
from etf_engine.sources.akshare.history import AkshareETFHistorySource
from etf_engine.sources.akshare.holdings import AkshareETFHoldingSource
from etf_engine.sources.akshare.index_data import (
    AkshareIndexCatalogSource,
    AkshareIndexConstituentSource,
    AkshareIndexQuoteSource,
)
from etf_engine.sources.akshare.index_valuation import AkshareIndexValuationSource
from etf_engine.sources.akshare.industry import AkshareStockIndustrySource
from etf_engine.sources.akshare.margin import AkshareMarginBalanceSource
from etf_engine.sources.akshare.nav import AkshareETFNavHistorySource, AkshareETFNavSource
from etf_engine.sources.akshare.quotes import AkshareETFQuoteSource
from etf_engine.sources.akshare.valuation import AkshareMarketValuationSource
from etf_engine.sources.master import UnifiedETFMasterSource
from etf_engine.sources.sse.market_turnover import SSEMarketTurnoverSource
from etf_engine.sources.sse.shares import SSEETFShareSource
from etf_engine.sources.szse.market_turnover import SZSEMarketTurnoverSource
from etf_engine.sources.szse.shares import SZSEETFShareSource


from etf_engine.sources.westock.history import WestockETFHistorySource
from etf_engine.sources.westock.holdings import WestockETFHoldingSource
from etf_engine.sources.westock.nav import WestockETFNavHistorySource, WestockETFNavSource
from etf_engine.sources.westock.quotes import WestockETFQuoteSource


@dataclass(frozen=True, slots=True)
class SourceRegistry:
    """V1 默认能力注册表。

    后续接入 HiThink / Wind / Choice / WeStock 时，不修改 Service 层；
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
    calendar_source = AkshareTradingCalendarSource
    industry_source = AkshareStockIndustrySource
    index_catalog_source = AkshareIndexCatalogSource
    index_constituent_source = AkshareIndexConstituentSource
    index_quote_source = AkshareIndexQuoteSource
    index_benchmark_source = AkshareFundProfileSource
    fund_profile_source = AkshareFundProfileSource
    corporate_action_source = EastmoneyFundActionSource
    share_sources = (SSEETFShareSource, SZSEETFShareSource)

    #: WeStock (腾讯自选股源) 备选与交叉校验适配器
    westock_quote_source = WestockETFQuoteSource
    westock_history_source = WestockETFHistorySource
    westock_nav_source = WestockETFNavSource
    westock_nav_history_source = WestockETFNavHistorySource
    westock_holding_source = WestockETFHoldingSource

    #: 看盘台（docs/WATCHBOARD.md）市场层能力。
    market_turnover_sources = (SSEMarketTurnoverSource, SZSEMarketTurnoverSource)
    margin_source = AkshareMarginBalanceSource
    valuation_source = AkshareMarketValuationSource
    market_activity_source = AkshareMarketActivitySource
    index_valuation_source = AkshareIndexValuationSource
    fund_issuance_source = AkshareFundIssuanceSource


registry = SourceRegistry()
