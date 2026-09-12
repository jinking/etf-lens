"""市场层适配器解析测试（纯函数，不访问网络）。

重点验证三件事：单位换算、口径缺失保持 NULL、缺列/缺值时报错或留痕。
"""

from datetime import date, datetime

import pandas as pd

from etf_engine.domain.enums import Exchange
from etf_engine.sources.akshare.activity import parse_activity_frame
from etf_engine.sources.akshare.margin import parse_margin_frame
from etf_engine.sources.akshare.valuation import (
    ALL_A_INDEX_ID,
    parse_valuation_frame,
)
from etf_engine.sources.sse.market_turnover import parse_sse_deal_daily
from etf_engine.sources.szse.market_turnover import parse_szse_summary

FETCHED_AT = datetime(2026, 9, 12, 10, 0)


def _sse_frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {"单日情况": "挂牌数", "股票": 2359.0, "主板A": 1701.0, "科创板": 617.0},
            {"单日情况": "市价总值", "股票": 689915.12, "主板A": 523540.34, "科创板": 165267.98},
            {"单日情况": "流通市值", "股票": 609863.74, "主板A": 503409.81, "科创板": 105711.42},
            {"单日情况": "成交金额", "股票": 9599.84, "主板A": 6978.17, "科创板": 2619.74},
            {"单日情况": "换手率", "股票": 1.3915, "主板A": 1.3329, "科创板": 1.5852},
        ]
    )


def test_sse_turnover_converts_yi_to_yuan():
    row, issues = parse_sse_deal_daily(
        _sse_frame(), trade_date=date(2026, 9, 11), fetched_at=FETCHED_AT
    )

    assert row is not None
    assert row.exchange == Exchange.SSE
    assert float(row.turnover_amount) == 9599.84 * 1e8
    assert float(row.turnover_rate_pct) == 1.3915
    assert float(row.float_market_cap) == 609863.74 * 1e8
    assert row.source_meta.source == "sse"
    assert issues == []


def test_sse_turnover_without_amount_is_reported_not_invented():
    frame = _sse_frame()
    frame = frame[frame["单日情况"] != "成交金额"]

    row, issues = parse_sse_deal_daily(frame, trade_date=date(2026, 9, 11), fetched_at=FETCHED_AT)

    assert row is None
    assert issues and issues[0].rule_name == "market_turnover_missing_field"


def test_szse_turnover_keeps_turnover_rate_null():
    frame = pd.DataFrame(
        [
            {
                "证券类别": "股票",
                "数量": 2939,
                "成交金额": 1.014578e12,
                "总市值": 4.337863e13,
                "流通市值": 3.696080e13,
            },
            {
                "证券类别": "基金",
                "数量": 1044,
                "成交金额": 1.317193e11,
                "总市值": 1.674403e12,
                "流通市值": 1.651246e12,
            },
        ]
    )

    row, issues = parse_szse_summary(frame, trade_date=date(2026, 9, 11), fetched_at=FETCHED_AT)

    assert row is not None
    assert row.exchange == Exchange.SZSE
    assert float(row.turnover_amount) == 1.014578e12  # 上游已是元，不再换算
    assert row.turnover_rate_pct is None  # 深交所不披露，保持 NULL
    assert float(row.listing_count) == 2939
    assert issues == []


def test_szse_missing_stock_row_is_reported():
    frame = pd.DataFrame([{"证券类别": "基金", "成交金额": 1.0}])
    row, issues = parse_szse_summary(frame, trade_date=date(2026, 9, 11), fetched_at=FETCHED_AT)
    assert row is None
    assert issues and issues[0].rule_name == "market_turnover_missing_field"


def test_margin_parsing_filters_range_and_keeps_nulls():
    frame = pd.DataFrame(
        [
            {
                "日期": "2026-09-09",
                "融资买入额": 7.9e10,
                "融资余额": 1.337e12,
                "融券余量": None,
                "融券余额": 1.86e10,
                "融资融券余额": 1.356e12,
            },
            {
                "日期": "2026-09-10",
                "融资买入额": 7.2e10,
                "融资余额": 1.337e12,
                "融券余量": None,
                "融券余额": 1.86e10,
                "融资融券余额": 1.355e12,
            },
            {
                "日期": "2026-09-11",
                "融资买入额": None,
                "融资余额": None,
                "融券余量": None,
                "融券余额": None,
                "融资融券余额": None,
            },
        ]
    )

    rows, issues = parse_margin_frame(
        frame,
        exchange=Exchange.SSE,
        fetched_at=FETCHED_AT,
        start_date=date(2026, 9, 10),
    )

    assert [row.trade_date.isoformat() for row in rows] == ["2026-09-10"]
    # 余额为空的交易日不入库，而是留一条 issue；NULL 不能被当成 0
    assert any(issue.rule_name == "margin_balance_null" for issue in issues)
    assert rows[0].securities_lending_balance is not None


def test_margin_missing_column_raises():
    frame = pd.DataFrame([{"日期": "2026-09-10", "融资余额": 1.0}])
    try:
        parse_margin_frame(frame, exchange=Exchange.SSE, fetched_at=FETCHED_AT)
    except RuntimeError as exc:
        assert "融资融券余额" in str(exc)
    else:  # pragma: no cover - 缺列必须显式失败
        raise AssertionError("缺列时应当报错")


def test_valuation_parsing_keeps_source_quantiles():
    frame = pd.DataFrame(
        [
            {
                "date": "2026-09-11",
                "middlePETTM": 36.37,
                "averagePETTM": 58.3,
                "middlePELYR": 38.3,
                "averagePELYR": 62.37,
                "close": 4510.16,
                "quantileInAllHistoryMiddlePeTtm": 0.50142,
                "quantileInRecent10YearsMiddlePeTtm": 0.64728,
                "quantileInAllHistoryMiddlePeLyr": 0.50579,
                "quantileInRecent10YearsMiddlePeLyr": 0.63696,
            },
            {  # 上游早期行常常整行空值
                "date": "2005-01-31",
                "middlePETTM": None,
                "averagePETTM": None,
                "middlePELYR": None,
                "averagePELYR": None,
                "close": None,
                "quantileInAllHistoryMiddlePeTtm": None,
                "quantileInRecent10YearsMiddlePeTtm": None,
                "quantileInAllHistoryMiddlePeLyr": None,
                "quantileInRecent10YearsMiddlePeLyr": None,
            },
        ]
    )

    rows, issues = parse_valuation_frame(frame, fetched_at=FETCHED_AT)

    assert len(rows) == 1
    assert rows[0].index_id == ALL_A_INDEX_ID
    assert float(rows[0].quantile_ttm_median_10y) == 0.64728
    assert any(issue.rule_name == "valuation_row_empty" for issue in issues)


def test_activity_parsing_uses_upstream_statistic_date():
    frame = pd.DataFrame(
        [
            {"item": "上涨", "value": 604.0},
            {"item": "下跌", "value": 4567.0},
            {"item": "平盘", "value": 36.0},
            {"item": "停牌", "value": 12.0},
            {"item": "涨停", "value": 40.0},
            {"item": "跌停", "value": 21.0},
            {"item": "真实涨停", "value": 36.0},
            {"item": "真实跌停", "value": 19.0},
            {"item": "活跃度", "value": "11.57%"},
            {"item": "统计日期", "value": "2026-09-11 15:00:00"},
        ]
    )

    rows, issues = parse_activity_frame(frame, fetched_at=FETCHED_AT)

    assert len(rows) == 1
    assert rows[0].trade_date == date(2026, 9, 11)
    assert float(rows[0].activity_pct) == 11.57
    assert float(rows[0].limit_up_count) == 40
    assert issues == []


def test_activity_without_statistic_date_is_not_stored():
    frame = pd.DataFrame([{"item": "上涨", "value": 604.0}])
    rows, issues = parse_activity_frame(frame, fetched_at=FETCHED_AT)
    assert rows == []
    assert issues and issues[0].rule_name == "activity_date_missing"
