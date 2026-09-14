from datetime import date, timedelta

import pytest

from etf_engine.sources.westock.history import WestockETFHistorySource
from etf_engine.sources.westock.holdings import WestockETFHoldingSource
from etf_engine.sources.westock.nav import WestockETFNavHistorySource
from etf_engine.sources.westock.quotes import WestockETFQuoteSource


@pytest.mark.live
def test_westock_live_quote_and_holdings():
    """实时调用 WeStock 抓取 510300.SH 的行情与持仓。"""
    quote_source = WestockETFQuoteSource()
    quotes = quote_source.fetch_quotes(security_ids=["510300.SH"])
    assert len(quotes) == 1
    q = quotes[0]
    assert q.security_id == "510300.SH"
    assert q.close is not None and q.close > 0
    assert q.name is not None and "300" in q.name

    holding_source = WestockETFHoldingSource()
    holdings = holding_source.fetch_holdings("510300.SH")
    assert len(holdings) >= 10
    top1 = holdings[0]
    assert top1.etf_id == "510300.SH"
    assert top1.stock_id.endswith((".SH", ".SZ"))
    assert top1.weight_pct is not None and top1.weight_pct > 0


@pytest.mark.live
def test_westock_live_history_and_nav():
    """实时调用 WeStock 抓取 510300.SH 的近 5 个交易日日K与净值。"""
    today = date.today()
    start_date = today - timedelta(days=10)

    hist_source = WestockETFHistorySource()
    bars = hist_source.fetch_history("510300.SH", start_date=start_date, end_date=today)
    assert len(bars) >= 1
    assert bars[0].close is not None and bars[0].close > 0

    nav_source = WestockETFNavHistorySource()
    navs = nav_source.fetch_nav_history("510300.SH", start_date=start_date, end_date=today)
    assert len(navs) >= 1
    assert navs[0].unit_nav is not None and navs[0].unit_nav > 0
