from datetime import date, datetime
from decimal import Decimal

import pandas as pd
import pytest

from etf_engine.sources.akshare.index_data import (
    parse_constituent_frame,
    parse_csindex_catalog,
    parse_fund_profile,
    parse_index_quote_frame,
    parse_sina_symbols,
)

FETCHED_AT = datetime(2026, 9, 12, 10, 0)


def test_catalog_parsing_skips_non_numeric_codes():
    frame = pd.DataFrame(
        [
            {"指数代码": "000300", "指数全称": "沪深300指数", "指数简称": "沪深300"},
            {"指数代码": "H30533", "指数全称": "某港股指数", "指数简称": "港股"},
        ]
    )

    assert parse_csindex_catalog(frame) == [("000300", "沪深300指数", "沪深300")]


def test_catalog_parsing_requires_expected_columns():
    with pytest.raises(RuntimeError):
        parse_csindex_catalog(pd.DataFrame([{"指数代码": "000300"}]))


def test_sina_symbols_are_keyed_by_six_digit_code():
    frame = pd.DataFrame([{"代码": "sh000300", "名称": "沪深300"}, {"代码": "sz399006"}])

    assert parse_sina_symbols(frame) == {"000300": "sh000300", "399006": "sz399006"}


def test_constituents_map_exchange_and_keep_weights():
    frame = pd.DataFrame(
        [
            {"日期": "2026-08-31", "成分券代码": "600519", "成分券名称": "贵州茅台", "权重": 4.2},
            {"日期": "2026-08-31", "成分券代码": "00700", "成分券名称": "腾讯控股", "权重": 3.1},
            {"日期": "2026-08-31", "成分券代码": "300750", "成分券名称": "宁德时代", "权重": None},
            {"日期": "2026-08-31", "成分券代码": "999999", "成分券名称": "异常代码", "权重": 1.0},
        ]
    )

    constituents, issues = parse_constituent_frame(frame, index_id="000300", fetched_at=FETCHED_AT)

    # 5 位代码是港股，不是被补零的 A 股。
    assert [c.stock_id for c in constituents] == ["600519.SH", "00700.HK", "300750.SZ"]
    assert constituents[0].weight_pct == Decimal("4.2")
    assert [issue.rule_name for issue in issues] == ["constituent_code_out_of_scope"]


def test_index_quotes_are_filtered_to_the_requested_window():
    frame = pd.DataFrame(
        [
            {"date": "2026-06-01", "open": 1, "high": 2, "low": 0.5, "close": 1.5},
            {"date": "2026-09-11", "open": 2, "high": 3, "low": 1.5, "close": 2.5},
        ]
    )

    quotes = parse_index_quote_frame(
        frame,
        index_id="000300",
        fetched_at=FETCHED_AT,
        start_date=date(2026, 8, 1),
        end_date=date(2026, 9, 11),
    )

    assert [(q.trade_date, q.close) for q in quotes] == [(date(2026, 9, 11), Decimal("2.5"))]


def test_index_quotes_require_a_date_column():
    with pytest.raises(RuntimeError):
        parse_index_quote_frame(
            pd.DataFrame([{"close": 1.0}]), index_id="931151", fetched_at=FETCHED_AT
        )


PROFILE_HTML = """
<table>
  <tr><th>跟踪标的</th><td>&nbsp;中证500指数&nbsp;</td></tr>
  <tr><th>业绩比较基准</th><td>中证500指数收益率</td></tr>
</table>
"""


def test_fund_profile_extracts_tracking_target_and_benchmark():
    assert parse_fund_profile(PROFILE_HTML) == ("中证500指数", "中证500指数收益率")


def test_fund_profile_without_fields_returns_none():
    assert parse_fund_profile("<html><body>无字段</body></html>") == (None, None)


def test_fund_profile_strips_inner_tags():
    html = "<th>跟踪标的</th><td><a href='#'>创业板指数</a>(价格)</td>"

    assert parse_fund_profile(html)[0] == "创业板指数(价格)"
