from dataclasses import dataclass

from etf_engine.sources.akshare.history import AkshareETFHistorySource
from etf_engine.sources.akshare.quotes import AkshareETFQuoteSource
from etf_engine.sources.master import UnifiedETFMasterSource
from etf_engine.sources.sse.shares import SSEETFShareSource
from etf_engine.sources.szse.shares import SZSEETFShareSource


@dataclass(frozen=True, slots=True)
class SourceRegistry:
    """V1 默认能力注册表。

    后续接入 HiThink / Wind / Choice 时，不修改 Service 层；
    只扩展注册表与 capability policy。
    """

    master_source = UnifiedETFMasterSource
    quote_source = AkshareETFQuoteSource
    history_source = AkshareETFHistorySource
    share_sources = (SSEETFShareSource, SZSEETFShareSource)


registry = SourceRegistry()

