"""基准相对指标：口径不明即 NULL，窗口不足即 NULL。"""

from datetime import date

import pandas as pd
import pytest

from etf_engine.domain.enums import BenchmarkReturnBasis
from etf_engine.research.benchmark import (
    premium_stats,
    tracking_stats,
    tracking_stats_all_windows,
)


def _series(values: list[float], start=date(2026, 1, 1)) -> pd.Series:
    index = pd.date_range(start, periods=len(values), freq="B")
    return pd.Series(values, index=index)


def test_price_basis_gives_difference_error_and_both_returns():
    nav = _series([100 * 1.002**i for i in range(61)])
    benchmark = _series([100 * 1.001**i for i in range(61)])

    stats = tracking_stats(nav, benchmark, window=60, basis=BenchmarkReturnBasis.PRICE_INDEX)

    assert stats.reason is None
    assert stats.difference == pytest.approx(1.002**60 - 1.001**60)
    assert stats.error is not None
    assert stats.nav_return == pytest.approx(1.002**60 - 1)
    assert stats.benchmark_return == pytest.approx(1.001**60 - 1)


def test_unknown_basis_gives_null_difference_with_reason():
    nav = _series([1.0] * 61)
    benchmark = _series([100.0] * 61)

    stats = tracking_stats(nav, benchmark, window=60, basis=BenchmarkReturnBasis.UNKNOWN)

    assert stats.difference is None
    assert stats.reason == "benchmark_return_basis_unknown"


def test_short_history_reports_insufficient_alignment():
    nav = _series([1.0] * 10)
    benchmark = _series([100.0] * 10)

    stats = tracking_stats(nav, benchmark, window=60, basis=BenchmarkReturnBasis.PRICE_INDEX)

    assert stats.difference is None
    assert stats.error is None
    assert stats.reason == "insufficient_aligned_history"


def test_multiple_windows_are_independent():
    nav = _series([100 * 1.001**i for i in range(61)])
    benchmark = _series([100 * 1.001**i for i in range(61)])

    stats = tracking_stats_all_windows(
        nav, benchmark, basis=BenchmarkReturnBasis.PRICE_INDEX, windows=(20, 60, 250)
    )

    assert set(stats) == {20, 60, 250}
    assert stats[20].difference == pytest.approx(0, abs=1e-9)
    assert stats[60].difference == pytest.approx(0, abs=1e-9)
    assert stats[250].difference is None, "250 日窗口样本不足"


def test_premium_stats_measure_stability_not_level():
    stable = pd.Series([0.001, 0.0012, 0.0009, 0.0011])
    noisy = pd.Series([0.03, -0.02, 0.04, -0.01])

    stable_stats = premium_stats(stable, window=4)
    noisy_stats = premium_stats(noisy, window=4)

    assert stable_stats.std < noisy_stats.std
    assert abs(stable_stats.mean) < abs(noisy_stats.mean)
    assert stable_stats.sample_size == 4


def test_premium_stats_without_samples_is_null():
    stats = premium_stats(pd.Series([], dtype="float64"), window=20)

    assert stats.mean is None
    assert stats.std is None
    assert stats.sample_size == 0
