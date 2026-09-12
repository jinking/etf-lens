from datetime import date, datetime

import pytest

from etf_engine.domain.calendar import MarketCalendar


def _calendar() -> MarketCalendar:
    # 2026-09-11 是周五，2026-09-12 是周六，2026-09-14 是下一个交易日。
    return MarketCalendar.from_iterable(
        [
            date(2026, 9, 9),
            date(2026, 9, 10),
            date(2026, 9, 11),
            date(2026, 9, 14),
            date(2026, 9, 15),
        ]
    )


def test_calendar_requires_at_least_one_day():
    with pytest.raises(ValueError):
        MarketCalendar.from_iterable([])


def test_is_trading_day_knows_weekends():
    calendar = _calendar()

    assert calendar.is_trading_day(date(2026, 9, 11)) is True
    assert calendar.is_trading_day(date(2026, 9, 12)) is False


def test_latest_closed_trading_day_falls_back_on_saturday():
    """周六运行必须回退到周五，而不是把周六当交易日（历史 bug）。"""
    calendar = _calendar()

    assert calendar.latest_closed_trading_day(datetime(2026, 9, 12, 9, 39)) == date(2026, 9, 11)


def test_latest_closed_trading_day_uses_previous_day_before_data_ready_hour():
    calendar = _calendar()

    assert calendar.latest_closed_trading_day(datetime(2026, 9, 14, 9, 0)) == date(2026, 9, 11)
    assert calendar.latest_closed_trading_day(datetime(2026, 9, 14, 18, 0)) == date(2026, 9, 14)


def test_trading_days_back_walks_trading_days_not_calendar_days():
    calendar = _calendar()

    assert calendar.trading_days_back(date(2026, 9, 14), 3) == [
        date(2026, 9, 14),
        date(2026, 9, 11),
        date(2026, 9, 10),
    ]


def test_trading_days_back_stops_at_calendar_start():
    calendar = _calendar()

    assert calendar.trading_days_back(date(2026, 9, 10), 5) == [date(2026, 9, 10), date(2026, 9, 9)]


def test_covers_reports_dates_outside_the_calendar():
    calendar = _calendar()

    assert calendar.covers(date(2026, 9, 11)) is True
    assert calendar.covers(date(2026, 9, 12)) is True
    assert calendar.covers(date(2027, 1, 4)) is False
