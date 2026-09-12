from datetime import date, datetime
from decimal import Decimal

import pandas as pd
import pytest

from etf_engine.sources.akshare.nav import parse_nav_history_frame

FETCHED_AT = datetime(2026, 9, 12, 10, 0)


def test_nav_history_parses_dates_and_keeps_adjusted_nav_null():
    frame = pd.DataFrame(
        [
            {"净值日期": "2026-09-10", "单位净值": "1.1061", "累计净值": "3.3183"},
            {"净值日期": "2026-09-11", "单位净值": "1.0913", "累计净值": "3.2739"},
        ]
    )

    navs, issues = parse_nav_history_frame(frame, security_id="588200.SH", fetched_at=FETCHED_AT)

    assert issues == []
    assert [(nav.nav_date, nav.unit_nav) for nav in navs] == [
        (date(2026, 9, 10), Decimal("1.1061")),
        (date(2026, 9, 11), Decimal("1.0913")),
    ]
    assert all(nav.adjusted_nav is None for nav in navs)
    assert all(nav.security_id == "588200.SH" for nav in navs)


def test_nav_history_skips_invalid_dates_and_navs_without_losing_the_rest():
    frame = pd.DataFrame(
        [
            {"净值日期": "2026-09-11", "单位净值": "1.0913"},
            {"净值日期": "not-a-date", "单位净值": "1.0"},
            {"净值日期": "2026-09-09", "单位净值": "0"},
            {"净值日期": "2026-09-08", "单位净值": None},
        ]
    )

    navs, issues = parse_nav_history_frame(frame, security_id="588200.SH", fetched_at=FETCHED_AT)

    assert [nav.nav_date for nav in navs] == [date(2026, 9, 11)]
    assert {issue.rule_name for issue in issues} == {"nav_history_date_invalid", "nav_positive"}


def test_nav_history_requires_expected_columns():
    with pytest.raises(RuntimeError):
        parse_nav_history_frame(
            pd.DataFrame([{"单位净值": "1"}]), security_id="588200.SH", fetched_at=FETCHED_AT
        )
