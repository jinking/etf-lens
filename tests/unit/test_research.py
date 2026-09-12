import pandas as pd

from etf_engine.research.flow import calculate_flow
from etf_engine.research.performance import simple_return
from etf_engine.research.risk import current_drawdown, max_drawdown


def test_simple_return():
    s = pd.Series([100, 101, 103])
    assert round(simple_return(s, 2), 6) == 0.03


def test_drawdown():
    s = pd.Series([100, 120, 90, 100])
    assert round(max_drawdown(s), 6) == -0.25
    assert round(current_drawdown(s), 6) == round(100 / 120 - 1, 6)


def test_flow():
    shares = pd.Series([100, 101, 102, 103])
    nav = pd.Series([1.0, 1.0, 1.1, 1.2])
    result = calculate_flow(shares, nav)
    assert result.share_change_1d == 1.0
    assert result.consecutive_share_inflow_days == 3
    assert result.estimated_net_subscription_1d == 1.2
