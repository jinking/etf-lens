import pytest

from etf_engine.sources.akshare.calendar import AkshareTradingCalendarSource
from etf_engine.sources.akshare.history import AkshareETFHistorySource
from etf_engine.sources.akshare.holdings import AkshareETFHoldingSource
from etf_engine.sources.akshare.nav import AkshareETFNavSource
from etf_engine.sources.akshare.quotes import AkshareETFQuoteSource
from etf_engine.sources.base import (
    ETFHistorySource,
    ETFHoldingSource,
    ETFMasterSource,
    ETFNavSource,
    ETFQuoteSource,
    ETFShareSource,
    TradingCalendarSource,
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


@pytest.mark.parametrize("source_cls", [AkshareETFNavSource])
def test_nav_sources_follow_contract(source_cls):
    source = source_cls()
    assert isinstance(source, ETFNavSource)
    assert hasattr(source, "fetch_navs")


@pytest.mark.parametrize("source_cls", [AkshareETFHoldingSource])
def test_holding_sources_follow_contract(source_cls):
    source = source_cls()
    assert isinstance(source, ETFHoldingSource)
    assert hasattr(source, "fetch_holdings")
    assert hasattr(source, "fetch_holdings_with_issues")


@pytest.mark.parametrize("source_cls", [AkshareTradingCalendarSource])
def test_calendar_sources_follow_contract(source_cls):
    source = source_cls()
    assert isinstance(source, TradingCalendarSource)
    assert hasattr(source, "fetch_trading_days")


def test_share_sources_expose_issue_variants():
    for source_cls in (SSEETFShareSource, SZSEETFShareSource):
        source = source_cls()
        assert hasattr(source, "fetch_shares_with_issues")
        assert source.source_name in {"sse", "szse"}


def test_registry_is_the_single_entry_point_for_adapters():
    from etf_engine.sources.registry import registry

    assert registry.quote_source is AkshareETFQuoteSource
    assert registry.nav_source is AkshareETFNavSource
    assert registry.calendar_source is AkshareTradingCalendarSource
    assert registry.holding_source is AkshareETFHoldingSource
