"""验证真实前向最大回撤（Forward Maximum Drawdown）计算函数。

与起点最大不利变动（MAE）区分：
- 100 -> 120 -> 105：真实最大回撤是 105/120 - 1 = -12.5%，而 MAE 是 105/100 - 1 = +5%
- 100 -> 90 -> 80：真实最大回撤是 80/100 - 1 = -20%
"""

import pandas as pd
import pytest

from etf_engine.research.regime_validation import (
    forward_max_drawdown,
    max_adverse_excursion,
)


def test_forward_max_drawdown_peak_within_forward():
    """100 -> 120 -> 105：高点在 forward 内部出现，最大回撤为 105/120 - 1 = -12.5%"""
    start = 100.0
    forward = pd.Series([120.0, 105.0])

    mdd = forward_max_drawdown(start, forward)
    assert mdd == pytest.approx(-0.125)

    mae = max_adverse_excursion(start, forward)
    assert mae == pytest.approx(0.05)


def test_forward_max_drawdown_monotonically_declining():
    """100 -> 90 -> 80：单调下跌，最大回撤为 80/100 - 1 = -20%"""
    start = 100.0
    forward = pd.Series([90.0, 80.0])

    mdd = forward_max_drawdown(start, forward)
    assert mdd == pytest.approx(-0.20)

    mae = max_adverse_excursion(start, forward)
    assert mae == pytest.approx(-0.20)


def test_forward_max_drawdown_monotonically_rising():
    """100 -> 110 -> 120：单调上涨，最大回撤为 0.0"""
    start = 100.0
    forward = pd.Series([110.0, 120.0])

    assert forward_max_drawdown(start, forward) == pytest.approx(0.0)
    assert max_adverse_excursion(start, forward) == pytest.approx(0.10)


def test_forward_max_drawdown_empty_or_invalid():
    """空序列或无效值安全处理"""
    assert forward_max_drawdown(100.0, pd.Series([], dtype=float)) == pytest.approx(0.0)
    assert forward_max_drawdown(0.0, pd.Series([10.0])) == pytest.approx(0.0)
