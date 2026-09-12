from datetime import date

import pandas as pd
import pytest

from etf_engine.research.exposure import calculate_top10_concentration
from etf_engine.research.flow import calculate_flow
from etf_engine.research.liquidity import (
    average_turnover_amount,
    bid_ask_spread,
    normalize_premium_discount,
)
from etf_engine.research.performance import simple_return
from etf_engine.research.risk import max_drawdown
from etf_engine.research.tracking import tracking_error


def test_premium_discount_is_normalized_from_close_and_iopv():
    assert normalize_premium_discount(4.968, 4.3825) == pytest.approx(0.1335995431)
    assert normalize_premium_discount(4.968, 0) is None


def test_liquidity_metrics_require_valid_quotes_and_complete_window():
    assert average_turnover_amount(pd.Series(range(1, 21)), 20) == 10.5
    assert average_turnover_amount(pd.Series(range(1, 20)), 20) is None
    assert bid_ask_spread(10, 10.02) == pytest.approx((0.02, 0.001998001998))
    assert bid_ask_spread(10.02, 10) is None


def test_top10_concentration_normalizes_percentage_weights():
    holdings = [
        {"stock_id": f"{index:06d}.SZ", "stock_name": str(index), "weight_pct": 8.5}
        for index in range(10)
    ]
    result = calculate_top10_concentration(holdings)

    assert result.concentration == pytest.approx(0.85)
    assert result.holdings[0].weight_pct == pytest.approx(0.085)


def test_top10_concentration_rejects_impossible_total_weight():
    holdings = [{"stock_id": "000001.SZ", "stock_name": "A", "weight_pct": 110}]
    result = calculate_top10_concentration(holdings)

    assert result.concentration is None
    assert result.reason == "holding_weight_conflict"


def test_top10_concentration_rejects_impossible_fractional_total_weight():
    holdings = [
        {"stock_id": f"{index:06d}.SZ", "stock_name": str(index), "weight_pct": 0.5}
        for index in range(3)
    ]
    result = calculate_top10_concentration(holdings)

    assert result.concentration is None
    assert result.reason == "holding_weight_conflict"


def test_flow_uses_daily_nav_weighted_subscription_sum():
    shares = pd.Series([100, 110, 105])
    nav = pd.Series([1.0, 2.0, 3.0])
    result = calculate_flow(shares, nav)

    assert result.share_change_1d == -5.0
    assert result.estimated_net_subscription_1d == -15.0
    assert result.estimated_net_subscription_2d == 5.0


def test_flow_does_not_substitute_short_history_for_20_days():
    shares = pd.Series(range(100, 112))
    nav = pd.Series([1.0] * 12)
    result = calculate_flow(shares, nav)

    assert result.share_change_20d is None
    assert result.estimated_net_subscription_20d is None


def test_return_and_drawdown_use_requested_trading_day_windows():
    prices = pd.Series(range(100, 161))

    assert simple_return(prices, 20) == pytest.approx(1 / 7)
    assert simple_return(prices, 60) == pytest.approx(0.6)
    assert max_drawdown(pd.Series([100, 120, 90, 100]), 4) == pytest.approx(-0.25)
    assert max_drawdown(pd.Series([100, 120, 90, 100]), 60) is None


def test_tracking_error_uses_aligned_nav_and_index_returns():
    index = pd.date_range(date(2026, 1, 1), periods=61, freq="D")
    nav = pd.Series([100 * 1.001**i for i in range(61)], index=index)
    benchmark = pd.Series([100 * 1.001**i for i in range(61)], index=index)

    assert tracking_error(nav, benchmark, window=60) == pytest.approx(0.0)


def test_tracking_error_requires_at_least_40_aligned_return_days():
    index = pd.date_range(date(2026, 1, 1), periods=40, freq="D")
    nav = pd.Series(range(100, 140), index=index)
    benchmark = pd.Series(range(200, 240), index=index)

    assert tracking_error(nav, benchmark, window=60) is None
