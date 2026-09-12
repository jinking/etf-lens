"""未复权序列的除权检测：宁可返回 None，不可给出错误的收益率。"""

from datetime import date

import pandas as pd
import pytest

from etf_engine.research.corporate_actions import (
    has_unadjusted_jump,
    has_unadjusted_jump_in_window,
)
from etf_engine.research.performance import annualized_volatility, simple_return
from etf_engine.research.risk import current_drawdown, max_drawdown
from etf_engine.research.tracking import tracking_error


def _split_series() -> pd.Series:
    """模拟 515880 在 2026-07-03 的 2:1 份额折算。"""
    return pd.Series([1.50, 1.52, 1.5774, 0.7885, 0.79, 0.80, 0.81])


def test_detects_a_split():
    assert has_unadjusted_jump(_split_series()) is True


def test_normal_series_is_not_flagged():
    assert has_unadjusted_jump(pd.Series([1.0, 1.02, 0.98, 1.05, 1.01])) is False


def test_limit_move_is_not_treated_as_a_split():
    """ETF 有 10% 涨跌停，±10% 是真实行情，不能当成除权。"""
    assert has_unadjusted_jump(pd.Series([1.0, 1.10, 0.99, 1.089])) is False


def test_window_detection_ignores_jumps_outside_the_window():
    series = pd.Series([1.0, 1.5, 0.75, 0.76, 0.77, 0.78])

    assert has_unadjusted_jump_in_window(series, periods=2) is False
    assert has_unadjusted_jump_in_window(series, periods=len(series) - 1) is True


def test_return_metrics_refuse_to_cross_a_split():
    series = _split_series()

    # 折算发生在第 3、4 个观测之间：跨过它的窗口一律不可用，
    # 只覆盖折算之后的窗口不受影响。
    assert simple_return(series, 4) is None
    assert simple_return(series, 2) == pytest.approx(0.81 / 0.79 - 1)


def test_volatility_and_drawdown_refuse_to_cross_a_split():
    series = _split_series()

    assert annualized_volatility(series, 5) is None
    assert max_drawdown(series, len(series)) is None
    assert current_drawdown(series) is None


def test_tracking_error_refuses_an_unadjusted_nav_series():
    index = pd.date_range(date(2026, 7, 1), periods=6, freq="D")
    nav = pd.Series([1.50, 1.52, 0.76, 0.77, 0.78, 0.79], index=index)
    benchmark = pd.Series([100, 101, 102, 103, 104, 105], index=index)

    assert tracking_error(nav, benchmark, window=5) is None


def test_tracking_error_still_works_without_corporate_actions():
    index = pd.date_range(date(2026, 1, 1), periods=61, freq="D")
    nav = pd.Series([100 * 1.001**i for i in range(61)], index=index)
    benchmark = pd.Series([100 * 1.001**i for i in range(61)], index=index)

    assert tracking_error(nav, benchmark, window=60) == pytest.approx(0.0)
