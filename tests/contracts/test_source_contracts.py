
import pytest

from etf_engine.sources.akshare.history import AkshareETFHistorySource
from etf_engine.sources.akshare.quotes import AkshareETFQuoteSource
from etf_engine.sources.base import (
    ETFHistorySource,
    ETFMasterSource,
    ETFQuoteSource,
    ETFShareSource,
)
from etf_engine.sources.master import UnifiedETFMasterSource
from etf_engine.sources.sse.shares import SSEETFShareSource
from etf_engine.sources.szse.shares import SZSEETFShareSource


@pytest.mark.parametrize("source_cls", [AkshareETFQuoteSource])
def test_quote_sources_follow_contract(source_cls):
    source = source_cls()
    assert isinstance(source, ETFQuoteSource)
    assert hasattr(source, "fetch_quotes")


@pytest.mark.parametrize("source_cls", [AkshareETFHistorySource])
def test_history_sources_follow_contract(source_cls):
    source = source_cls()
    assert isinstance(source, ETFHistorySource)
    assert hasattr(source, "fetch_history")


@pytest.mark.parametrize("source_cls", [SSEETFShareSource, SZSEETFShareSource])
def test_share_sources_follow_contract(source_cls):
    source = source_cls()
    assert isinstance(source, ETFShareSource)
    assert hasattr(source, "fetch_shares")


@pytest.mark.parametrize("source_cls", [UnifiedETFMasterSource])
def test_master_sources_follow_contract(source_cls):
    source = source_cls()
    assert isinstance(source, ETFMasterSource)
    assert hasattr(source, "fetch_masters")


