from datetime import date, datetime
from decimal import Decimal

import pandas as pd
import pytest

from etf_engine.sources.akshare.holdings import parse_holdings_frame, parse_quarter_to_date

FETCHED_AT = datetime(2026, 9, 12, 10, 0)


def _frame(rows: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(rows)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("2026年1季度股票投资明细", date(2026, 3, 31)),
        ("2026年2季度股票投资明细", date(2026, 6, 30)),
        ("2026年3季度股票投资明细", date(2026, 9, 30)),
        ("2026年4季度股票投资明细", date(2026, 12, 31)),
    ],
)
def test_quarter_end_dates(raw, expected):
    assert parse_quarter_to_date(raw) == expected


def test_unparsable_quarter_is_rejected_instead_of_using_today():
    """历史实现在解析失败时静默返回当天日期，等于伪造报告期。"""
    with pytest.raises(ValueError):
        parse_quarter_to_date("2026年中报")


def test_holdings_keep_hong_kong_codes_instead_of_faking_shenzhen_codes():
    frame = _frame(
        [
            {
                "股票代码": "01801",
                "股票名称": "信达生物",
                "占净值比例": 10.32,
                "持股数": 3420.5,
                "持仓市值": 256409.08,
                "季度": "2026年1季度股票投资明细",
            }
        ]
    )

    result = parse_holdings_frame(frame, security_id="513120.SH", fetched_at=FETCHED_AT)

    assert result.holdings[0].stock_id == "01801.HK"


def test_holdings_pick_the_latest_quarter_not_the_first_row():
    """东方财富返回的表是升序，取 iloc[0] 会拿到最旧的一期。"""
    frame = _frame(
        [
            {
                "股票代码": "600519",
                "股票名称": "贵州茅台",
                "占净值比例": 5.0,
                "季度": "2026年1季度股票投资明细",
            },
            {
                "股票代码": "300750",
                "股票名称": "宁德时代",
                "占净值比例": 6.0,
                "季度": "2026年2季度股票投资明细",
            },
        ]
    )

    result = parse_holdings_frame(frame, security_id="510300.SH", fetched_at=FETCHED_AT)

    assert result.report_date == date(2026, 6, 30)
    assert [holding.stock_id for holding in result.holdings] == ["300750.SZ"]


def test_holdings_do_not_fabricate_disclosure_date():
    frame = _frame(
        [
            {
                "股票代码": "600519",
                "股票名称": "贵州茅台",
                "占净值比例": 5.0,
                "季度": "2026年1季度股票投资明细",
            }
        ]
    )

    result = parse_holdings_frame(frame, security_id="510300.SH", fetched_at=FETCHED_AT)

    assert result.holdings[0].report_date == date(2026, 3, 31)
    assert result.holdings[0].disclosure_date is None


def test_holdings_are_sorted_by_weight_and_capped_at_top_ten():
    frame = _frame(
        [
            {
                "股票代码": f"{index:06d}",
                "股票名称": f"股票{index}",
                "占净值比例": float(index),
                "季度": "2026年2季度股票投资明细",
            }
            for index in range(1, 13)
        ]
    )

    result = parse_holdings_frame(frame, security_id="510300.SH", fetched_at=FETCHED_AT)

    assert len(result.holdings) == 10
    assert result.holdings[0].stock_id == "000012.SZ"
    assert result.holdings[-1].stock_id == "000003.SZ"


def test_one_bad_row_does_not_drop_the_whole_etf():
    """北交所/异常代码过去会让整只 ETF 的持仓全部丢失。"""
    frame = _frame(
        [
            {
                "股票代码": "600519",
                "股票名称": "贵州茅台",
                "占净值比例": 9.0,
                "季度": "2026年2季度股票投资明细",
            },
            {
                "股票代码": float("nan"),
                "股票名称": "坏行",
                "占净值比例": 8.0,
                "季度": "2026年2季度股票投资明细",
            },
            {
                "股票代码": "920002",
                "股票名称": "北交所标的",
                "占净值比例": 7.0,
                "季度": "2026年2季度股票投资明细",
            },
        ]
    )

    result = parse_holdings_frame(frame, security_id="159915.SZ", fetched_at=FETCHED_AT)

    assert [holding.stock_id for holding in result.holdings] == ["600519.SH", "920002.BJ"]
    assert [issue.rule_name for issue in result.issues] == ["holding_stock_code_missing"]


def test_numeric_stock_codes_read_as_floats_are_normalized():
    frame = _frame(
        [
            {
                "股票代码": 300750.0,
                "股票名称": "宁德时代",
                "占净值比例": 5.0,
                "季度": "2026年2季度股票投资明细",
            }
        ]
    )

    result = parse_holdings_frame(frame, security_id="510300.SH", fetched_at=FETCHED_AT)

    assert result.holdings[0].stock_id == "300750.SZ"
    assert result.holdings[0].weight_pct == Decimal("5.0")


def test_missing_columns_are_reported_loudly():
    with pytest.raises(RuntimeError):
        parse_holdings_frame(
            _frame([{"股票名称": "x"}]), security_id="510300.SH", fetched_at=FETCHED_AT
        )
