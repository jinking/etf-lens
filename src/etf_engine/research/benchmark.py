"""基准相对指标：跟踪差异 / 跟踪误差 / 折溢价稳定性。

与绝对收益分开命名：``nav_return``（基金净值口径）、``price_return``（二级市场价格
口径）、``benchmark_return``（基准口径）三者不能混。基准口径未知时一律返回 NULL +
原因，不拿价格指数口径假装算得出来（详见 ``docs/CORPORATE_ACTIONS.md``）。
"""

from dataclasses import dataclass

import pandas as pd

from etf_engine.domain.enums import BenchmarkReturnBasis
from etf_engine.research.tracking import tracking_difference, tracking_error

#: 跟踪指标窗口（交易日）。
WINDOWS: tuple[int, ...] = (20, 60, 250)


@dataclass(frozen=True, slots=True)
class TrackingStats:
    window: int
    difference: float | None
    error: float | None
    nav_return: float | None
    benchmark_return: float | None
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class PremiumStats:
    window: int
    mean: float | None
    std: float | None
    abs_mean: float | None
    sample_size: int


def _aligned_returns(
    nav: pd.Series, index_close: pd.Series, window: int
) -> tuple[pd.Series, pd.Series] | None:
    nav_values = pd.to_numeric(nav, errors="coerce").dropna()
    index_values = pd.to_numeric(index_close, errors="coerce").dropna()
    nav_values = nav_values[nav_values > 0]
    index_values = index_values[index_values > 0]
    if nav_values.empty or index_values.empty:
        return None
    aligned = pd.concat(
        [nav_values.rename("nav"), index_values.rename("index")], axis=1, join="inner"
    ).dropna()
    if len(aligned) < window + 1:
        return None
    return aligned["nav"].tail(window + 1), aligned["index"].tail(window + 1)


def tracking_stats(
    nav: pd.Series,
    index_close: pd.Series,
    *,
    window: int,
    basis: BenchmarkReturnBasis,
) -> TrackingStats:
    """单个窗口的跟踪差异/跟踪误差/两端收益。"""
    difference, reason = tracking_difference(nav, index_close, window=window, basis=basis)
    error = tracking_error(nav, index_close, window=window)
    aligned = _aligned_returns(nav, index_close, window)
    if aligned is None:
        return TrackingStats(
            window, difference, error, None, None, reason or "insufficient_aligned_history"
        )

    nav_values, index_values = aligned
    nav_return = float(nav_values.iloc[-1] / nav_values.iloc[0] - 1)
    benchmark_return = float(index_values.iloc[-1] / index_values.iloc[0] - 1)
    return TrackingStats(window, difference, error, nav_return, benchmark_return, reason)


def tracking_stats_all_windows(
    nav: pd.Series,
    index_close: pd.Series,
    *,
    basis: BenchmarkReturnBasis,
    windows: tuple[int, ...] = WINDOWS,
) -> dict[int, TrackingStats]:
    return {
        window: tracking_stats(nav, index_close, window=window, basis=basis) for window in windows
    }


def premium_stats(premium_pct: pd.Series, *, window: int) -> PremiumStats:
    """折溢价稳定性：均值 / 标准差 / 绝对值均值。

    标准差衡量"折溢价是否稳定"，绝对均值衡量"偏离程度"；两者是不同的东西，
    所以分开返回，不合成一个分数。
    """
    values = pd.to_numeric(premium_pct, errors="coerce").dropna().tail(window)
    if values.empty:
        return PremiumStats(window, None, None, None, 0)
    return PremiumStats(
        window=window,
        mean=float(values.mean()),
        std=float(values.std(ddof=1)) if len(values) > 1 else None,
        abs_mean=float(values.abs().mean()),
        sample_size=int(len(values)),
    )
