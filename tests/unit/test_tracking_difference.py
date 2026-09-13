"""跟踪差异：基准口径不明时宁可不给数字。"""

from datetime import date

import pandas as pd
import pytest

from etf_engine.domain.enums import BenchmarkReturnBasis
from etf_engine.research.tracking import classify_benchmark_basis, tracking_difference


def test_classify_reads_the_disclosed_name():
    assert classify_benchmark_basis("沪深300全收益指数") is BenchmarkReturnBasis.TOTAL_RETURN_INDEX
    assert (
        classify_benchmark_basis("中证500净收益指数") is BenchmarkReturnBasis.NET_TOTAL_RETURN_INDEX
    )
    assert classify_benchmark_basis("创业板指数(价格)") is BenchmarkReturnBasis.PRICE_INDEX
    assert classify_benchmark_basis("上证科创板芯片指数") is BenchmarkReturnBasis.UNKNOWN
    assert classify_benchmark_basis(None) is BenchmarkReturnBasis.UNKNOWN


def test_unknown_basis_refuses_to_compute():
    nav = pd.Series([1.0] * 61)
    index = pd.Series([100.0] * 61)

    value, reason = tracking_difference(nav, index, window=60)

    assert value is None
    assert reason == "benchmark_return_basis_unknown"


def test_total_return_basis_is_not_silently_treated_as_price():
    nav = pd.Series([1.0] * 61)
    index = pd.Series([100.0] * 61)

    value, reason = tracking_difference(
        nav, index, window=60, basis=BenchmarkReturnBasis.TOTAL_RETURN_INDEX
    )

    assert value is None
    assert reason == "total_return_basis_not_supported_yet"


def test_price_basis_computes_the_gap():
    nav = pd.Series([100 * 1.002**i for i in range(61)])
    index = pd.Series([100 * 1.001**i for i in range(61)])

    value, reason = tracking_difference(
        nav, index, window=60, basis=BenchmarkReturnBasis.PRICE_INDEX
    )

    assert reason is None
    assert value == pytest.approx(100 * 1.002**60 / 100 - (100 * 1.001**60 / 100))
    assert value > 0, "净值涨得比价格指数快，跟踪差异为正"


def test_unadjusted_nav_series_is_refused():
    """未复权净值跨折算：跟踪差异同样不可用（不能拿错误序列算差异）。"""
    index = pd.date_range(date(2026, 7, 1), periods=6, freq="D")
    nav = pd.Series([1.50, 1.52, 0.76, 0.77, 0.78, 0.79], index=index)
    benchmark = pd.Series([100, 101, 102, 103, 104, 105], index=index)

    value, reason = tracking_difference(
        nav, benchmark, window=5, basis=BenchmarkReturnBasis.PRICE_INDEX
    )

    assert value is None
    assert reason == "nav_not_adjusted_for_corporate_actions"


def test_insufficient_alignment_is_reported():
    nav = pd.Series([1.0] * 10)
    index = pd.Series([100.0] * 10)

    value, reason = tracking_difference(
        nav, index, window=60, basis=BenchmarkReturnBasis.PRICE_INDEX
    )

    assert value is None
    assert reason == "insufficient_aligned_history"
