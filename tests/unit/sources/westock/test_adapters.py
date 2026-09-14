from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from etf_engine.sources.westock.history import WestockETFHistorySource
from etf_engine.sources.westock.holdings import WestockETFHoldingSource
from etf_engine.sources.westock.nav import WestockETFNavHistorySource, WestockETFNavSource
from etf_engine.sources.westock.quotes import WestockETFQuoteSource


def test_quote_source_parsing():
    mock_client = MagicMock()
    mock_output = """
#### sh510300

| code | name | date | closePrice | changePct | turnoverVolume | turnoverValue | turnoverRate | nav | disc | size | shares |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| sh510300 | 沪深300ETF华泰柏瑞 | 2026-09-14 | 4.55 | -0.59 | 6291774 | 2863784490 | 2.69 | 4.62 | -0.05 | 107088100362.29 | 23190787700 |
"""
    mock_client.execute.return_value = mock_output
    # 复用真实解析方法
    from etf_engine.sources.westock.client import WestockClient
    mock_client.parse_etf_details.side_effect = WestockClient.parse_etf_details

    source = WestockETFQuoteSource(client=mock_client)
    quotes = source.fetch_quotes(security_ids=["510300.SH"])

    assert len(quotes) == 1
    q = quotes[0]
    assert q.security_id == "510300.SH"
    assert q.name == "沪深300ETF华泰柏瑞"
    assert q.trade_date == date(2026, 9, 14)
    assert q.close == Decimal("4.55")
    assert q.change_pct == Decimal("-0.59")
    assert q.iopv == Decimal("4.62")
    assert q.turnover_amount == Decimal("2863784490")
    assert q.source_meta.source == "westock"
    assert q.source_meta.upstream_source == "tencent"


def test_history_source_parsing():
    mock_client = MagicMock()
    mock_output = """
| date | open | last | high | low | volume | amount | exchange |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 2026-09-14 | 4.55 | 4.55 | 4.57 | 4.54 | 6291774 | 2863784490 | 2.69 |
| 2026-09-11 | 4.59 | 4.58 | 4.59 | 4.53 | 9666652 | 4409410000 | 4.17 |
| 2026-08-01 | 4.50 | 4.50 | 4.55 | 4.48 | 1000000 | 450000000 | 1.00 |
"""
    mock_client.execute.return_value = mock_output
    from etf_engine.sources.westock.client import WestockClient
    mock_client.parse_markdown_table.side_effect = WestockClient.parse_markdown_table

    source = WestockETFHistorySource(client=mock_client)
    history = source.fetch_history("510300.SH", start_date=date(2026, 9, 10), end_date=date(2026, 9, 15))

    assert len(history) == 2
    # 结果按日期升序
    assert history[0].trade_date == date(2026, 9, 11)
    assert history[0].close == Decimal("4.58")
    assert history[1].trade_date == date(2026, 9, 14)
    assert history[1].close == Decimal("4.55")


def test_nav_history_source_parsing():
    mock_client = MagicMock()
    mock_output = """
| date | nav | navChange | navChangePct | accNav |
| --- | --- | --- | --- | --- |
| 2026-09-11 | 4.58 | 0 | -0.82 | 0 |
| 2026-09-14 | 4.55 | 0 | -0.59 | 4.55 |
"""
    mock_client.execute.return_value = mock_output
    from etf_engine.sources.westock.client import WestockClient
    mock_client.parse_markdown_table.side_effect = WestockClient.parse_markdown_table

    source = WestockETFNavHistorySource(client=mock_client)
    navs = source.fetch_nav_history("510300.SH", start_date=date(2026, 9, 1), end_date=date(2026, 9, 15))

    assert len(navs) == 2
    assert navs[0].nav_date == date(2026, 9, 11)
    assert navs[0].unit_nav == Decimal("4.58")
    assert navs[0].adjusted_nav is None
    assert navs[1].nav_date == date(2026, 9, 14)
    assert navs[1].unit_nav == Decimal("4.55")


def test_holdings_source_parsing():
    mock_client = MagicMock()
    mock_output = """
**sh510300** (清单日期: 2026-09-14 00:00:00 +0800 CST)

| code | name | ratio |
| --- | --- | --- |
| 300308 | 中际旭创 | 4.49 |
| 600519 | 贵州茅台 | 3.09 |
"""
    mock_client.execute.return_value = mock_output
    from etf_engine.sources.westock.client import WestockClient
    mock_client.parse_holdings.side_effect = WestockClient.parse_holdings

    source = WestockETFHoldingSource(client=mock_client)
    holdings = source.fetch_holdings("510300.SH")

    assert len(holdings) == 2
    assert holdings[0].etf_id == "510300.SH"
    assert holdings[0].stock_id == "300308.SZ"
    assert holdings[0].stock_name == "中际旭创"
    assert holdings[0].weight_pct == Decimal("4.49")
    assert holdings[0].disclosure_date == date(2026, 9, 14)

    assert holdings[1].stock_id == "600519.SH"
    assert holdings[1].stock_name == "贵州茅台"
    assert holdings[1].weight_pct == Decimal("3.09")
