import pytest

from etf_engine.sources.akshare.quotes import AkshareETFQuoteSource


@pytest.mark.live
def test_akshare_quote_source_live():
    rows = AkshareETFQuoteSource().fetch_quotes()
    assert len(rows) > 0
