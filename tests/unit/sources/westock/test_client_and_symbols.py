import pytest

from etf_engine.sources.westock.client import WestockClient
from etf_engine.sources.westock.symbols import to_security_id, to_westock_symbol


def test_symbols_conversion():
    assert to_westock_symbol("510300.SH") == "sh510300"
    assert to_westock_symbol("159915.SZ") == "sz159915"

    assert to_security_id("sh510300") == "510300.SH"
    assert to_security_id("sz159915") == "159915.SZ"
    assert to_security_id("hk00700") == "00700.HK"

    with pytest.raises(ValueError):
        to_security_id("invalid123")


def test_parse_markdown_table():
    sample = """
| date | open | last | high | low | volume | amount | exchange |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 2026-09-14 | 4.55 | 4.55 | 4.57 | 4.54 | 6291774 | 2863784490 | 2.69 |
| 2026-09-11 | 4.59 | 4.58 | 4.59 | 4.53 | 9666652 | 4409410000 | 4.17 |
"""
    rows = WestockClient.parse_markdown_table(sample)
    assert len(rows) == 2
    assert rows[0]["date"] == "2026-09-14"
    assert rows[0]["last"] == "4.55"
    assert rows[1]["volume"] == "9666652"


def test_parse_holdings_with_date():
    sample = """
**sh510300** (清单日期: 2026-09-14 00:00:00 +0800 CST)

| code | name | ratio |
| --- | --- | --- |
| 300308 | 中际旭创 | 4.49 |
| 300750 | 宁德时代 | 3.21 |
"""
    holdings, d_date = WestockClient.parse_holdings(sample)
    assert d_date == "2026-09-14"
    assert len(holdings) == 2
    assert holdings[0]["code"] == "300308"
    assert holdings[0]["name"] == "中际旭创"
    assert holdings[0]["ratio"] == "4.49"


def test_parse_etf_details():
    sample = """
#### sh510300

| code | name | date | closePrice | changePct | turnoverVolume | turnoverValue | nav | disc | size | shares |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| sh510300 | 沪深300ETF华泰柏瑞 | 2026-09-14 | 4.55 | -0.59 | 6291774 | 2863784490 | 4.62 | -0.05 | 107088100362.29 | 23190787700 |

**持仓明细 (Top20)**

| code | name | ratio |
| --- | --- | --- |
| 300308 | 中际旭创 | 4.49 |
| 300750 | 宁德时代 | 3.21 |
"""
    parsed = WestockClient.parse_etf_details(sample)
    assert parsed["info"]["code"] == "sh510300"
    assert parsed["info"]["closePrice"] == "4.55"
    assert parsed["info"]["shares"] == "23190787700"
    assert len(parsed["holdings"]) == 2
    assert parsed["holdings"][0]["name"] == "中际旭创"
