from datetime import date, datetime
from decimal import Decimal

import pandas as pd
import pytest

from etf_engine.sources.akshare.nav import parse_nav_frame
from etf_engine.sources.sse.shares import SSE_SHARE_UNIT, parse_sse_rows
from etf_engine.sources.szse.shares import parse_szse_frame

FETCHED_AT = datetime(2026, 9, 12, 10, 0)


def test_sse_shares_use_upstream_stat_date_and_ten_thousand_unit():
    rows = [
        {
            "SEC_CODE": "510010",
            "SEC_NAME": "治理ETF",
            "STAT_DATE": "2026-09-11",
            "TOT_VOL": "13052.44",
        }
    ]

    shares, issues = parse_sse_rows(rows, fetched_at=FETCHED_AT, requested_asof=date(2026, 9, 11))

    assert issues == []
    assert shares[0].security_id == "510010.SH"
    assert shares[0].trade_date == date(2026, 9, 11)
    assert shares[0].shares == Decimal("13052.44") * SSE_SHARE_UNIT
    assert shares[0].nav is None, "上交所规模接口没有净值，必须留 NULL"


def test_sse_shares_flag_stat_date_behind_request():
    rows = [
        {"SEC_CODE": "510010", "SEC_NAME": "治理ETF", "STAT_DATE": "2026-09-10", "TOT_VOL": "1"}
    ]

    shares, issues = parse_sse_rows(rows, fetched_at=FETCHED_AT, requested_asof=date(2026, 9, 11))

    assert len(shares) == 1
    assert [issue.rule_name for issue in issues] == ["share_stat_date_behind_request"]


def test_sse_shares_skip_unparsable_rows_without_losing_the_rest():
    rows = [
        {"SEC_CODE": "510010", "SEC_NAME": "治理ETF", "STAT_DATE": "2026-09-11", "TOT_VOL": "1"},
        {"SEC_CODE": "abc", "SEC_NAME": "坏行", "STAT_DATE": "2026-09-11", "TOT_VOL": "1"},
        {"SEC_CODE": "510020", "SEC_NAME": "超大ETF", "STAT_DATE": "bad", "TOT_VOL": "2"},
        {"SEC_CODE": "510030", "SEC_NAME": "价值ETF", "STAT_DATE": "2026-09-11", "TOT_VOL": None},
    ]

    shares, issues = parse_sse_rows(rows, fetched_at=FETCHED_AT)

    assert [share.security_id for share in shares] == ["510010.SH"]
    assert {issue.rule_name for issue in issues} == {
        "share_code_unresolved",
        "share_stat_date_invalid",
        "share_volume_unresolved",
    }


def test_szse_shares_use_calendar_asof_instead_of_running_day():
    """快照没有自带日期，入库日期必须来自交易日历传入的 asof。"""
    frame = pd.DataFrame(
        [
            {
                "基金代码": "159915",
                "基金简称": "创业板ETF",
                "当前规模(份)": "84,925,835",
                "净值": "1.0574",
            },
            {
                "基金代码": "159916",
                "基金简称": "无净值ETF",
                "当前规模(份)": "1,000",
                "净值": None,
            },
        ]
    )

    shares, issues = parse_szse_frame(frame, asof=date(2026, 9, 11), fetched_at=FETCHED_AT)

    assert issues == []
    assert [share.trade_date for share in shares] == [date(2026, 9, 11)] * 2
    assert shares[0].shares == Decimal("84925835")
    assert shares[0].nav == Decimal("1.0574")
    assert shares[0].nav_source == "szse"
    assert shares[1].nav is None
    assert shares[1].nav_source is None


def test_szse_shares_never_produce_a_non_trading_day_date():
    frame = pd.DataFrame([{"基金代码": "159915", "基金简称": "创业板ETF", "当前规模(份)": "1"}])

    shares, _ = parse_szse_frame(frame, asof=date(2026, 9, 11), fetched_at=FETCHED_AT)

    assert shares[0].trade_date.weekday() < 5


def test_szse_shares_report_missing_volume_column():
    frame = pd.DataFrame([{"基金代码": "159915", "基金简称": "创业板ETF"}])

    shares, issues = parse_szse_frame(frame, asof=date(2026, 9, 11), fetched_at=FETCHED_AT)

    assert shares == []
    assert [issue.rule_name for issue in issues] == ["share_volume_unresolved"]


def test_nav_frame_parses_date_stamped_columns_only():
    frame = pd.DataFrame(
        [
            {
                "基金代码": "510300",
                "基金简称": "沪深300ETF",
                "2026-09-11-单位净值": "4.1234",
                "2026-09-11-累计净值": "9.8765",
                "2026-09-10-单位净值": "4.1000",
                "2026-09-10-累计净值": "9.8531",
            }
        ]
    )

    navs, issues = parse_nav_frame(frame, fetched_at=FETCHED_AT)

    assert issues == []
    assert [(nav.nav_date, nav.unit_nav) for nav in navs] == [
        (date(2026, 9, 11), Decimal("4.1234")),
        (date(2026, 9, 10), Decimal("4.1000")),
    ]
    assert all(nav.adjusted_nav is None for nav in navs), (
        "累计净值不是复权净值，不得当成 adjusted_nav"
    )


def test_nav_frame_can_filter_to_a_single_trading_day():
    frame = pd.DataFrame(
        [{"基金代码": "510300", "2026-09-11-单位净值": "4.1234", "2026-09-10-单位净值": "4.1000"}]
    )

    navs, _ = parse_nav_frame(frame, fetched_at=FETCHED_AT, trade_date=date(2026, 9, 10))

    assert [nav.nav_date for nav in navs] == [date(2026, 9, 10)]


def test_nav_frame_rejects_non_positive_nav():
    frame = pd.DataFrame([{"基金代码": "510300", "2026-09-11-单位净值": "0"}])

    navs, issues = parse_nav_frame(frame, fetched_at=FETCHED_AT)

    assert navs == []
    assert [issue.rule_name for issue in issues] == ["nav_positive"]


def test_nav_frame_requires_date_stamped_columns():
    with pytest.raises(RuntimeError):
        parse_nav_frame(
            pd.DataFrame([{"基金代码": "510300", "单位净值": "1"}]), fetched_at=FETCHED_AT
        )
