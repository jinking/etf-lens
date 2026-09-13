import numpy as np
import pandas as pd

from etf_engine.domain.enums import BenchmarkReturnBasis
from etf_engine.research.corporate_actions import has_unadjusted_jump

#: benchmark 名称里能确定口径的关键词（披露名称是事实，这里只做归类）。
_BASIS_KEYWORDS: tuple[tuple[str, BenchmarkReturnBasis], ...] = (
    ("全收益", BenchmarkReturnBasis.TOTAL_RETURN_INDEX),
    ("净收益", BenchmarkReturnBasis.NET_TOTAL_RETURN_INDEX),
    ("价格", BenchmarkReturnBasis.PRICE_INDEX),
)


def classify_benchmark_basis(index_name: str | None) -> BenchmarkReturnBasis:
    """判断基准收益口径。

    口径决定"跟踪差异"该怎么算：价格指数不含分红，拿它跟含分红的净值比，
    差异里混着分红，不是真实的跟踪表现。名称里看不出时返回 ``UNKNOWN``，
    调用方必须据此放弃计算，而不是默认成价格指数。
    """
    if not index_name:
        return BenchmarkReturnBasis.UNKNOWN
    text = str(index_name)
    for keyword, basis in _BASIS_KEYWORDS:
        if keyword in text:
            return basis
    return BenchmarkReturnBasis.UNKNOWN


def tracking_difference(
    nav: pd.Series,
    index_close: pd.Series,
    *,
    window: int = 60,
    basis: BenchmarkReturnBasis = BenchmarkReturnBasis.UNKNOWN,
) -> tuple[float | None, str | None]:
    """跟踪差异（NAV 累计收益 − 基准累计收益）。

    返回 ``(值, 不可用原因)``。基准口径未知时返回
    ``(None, "benchmark_return_basis_unknown")``——宁可不算，也不给一个
    混着分红口径的数字。
    """
    if basis is BenchmarkReturnBasis.UNKNOWN:
        return None, "benchmark_return_basis_unknown"
    if basis is BenchmarkReturnBasis.TOTAL_RETURN_INDEX:
        # 全收益指数与"净值+分红再投资"才是同一口径；我们不掌握该ETF的分红序列，
        # 因此对全收益基准暂不给跟踪差异（后续接入分红事实后再放开）。
        return None, "total_return_basis_not_supported_yet"

    nav_values, index_values = _aligned(nav, index_close)
    if nav_values is None or index_values is None:
        return None, "insufficient_aligned_history"
    if len(nav_values) < window + 1:
        return None, "insufficient_aligned_history"
    if has_unadjusted_jump(nav_values.tail(window + 1)):
        return None, "nav_not_adjusted_for_corporate_actions"

    nav_return = nav_values.iloc[-1] / nav_values.iloc[0] - 1
    index_return = index_values.iloc[-1] / index_values.iloc[0] - 1
    return float(nav_return - index_return), None


def _aligned(nav: pd.Series, index_close: pd.Series) -> tuple[pd.Series | None, pd.Series | None]:
    nav_values = pd.to_numeric(nav, errors="coerce").dropna()
    index_values = pd.to_numeric(index_close, errors="coerce").dropna()
    nav_values = nav_values[nav_values > 0]
    index_values = index_values[index_values > 0]
    if nav_values.empty or index_values.empty:
        return None, None
    aligned = pd.concat(
        [nav_values.rename("nav"), index_values.rename("index")], axis=1, join="inner"
    ).dropna()
    if aligned.empty:
        return None, None
    return aligned["nav"], aligned["index"]


def tracking_error(
    nav: pd.Series,
    index_close: pd.Series,
    window: int = 60,
    trading_days: int = 242,
    minimum_aligned_days: int = 40,
) -> float | None:
    """Annualized standard deviation of aligned ETF NAV and index daily return gaps."""
    nav_values = pd.to_numeric(nav, errors="coerce").dropna()
    index_values = pd.to_numeric(index_close, errors="coerce").dropna()
    nav_values = nav_values[nav_values > 0]
    index_values = index_values[index_values > 0]
    if nav_values.empty or index_values.empty:
        return None
    if has_unadjusted_jump(nav_values.tail(window + 1)):
        # 单位净值未复权：跨过份额折算/分红的区间算不出有意义的跟踪误差。
        return None

    daily_gaps = pd.concat(
        [nav_values.pct_change().rename("nav"), index_values.pct_change().rename("index")], axis=1
    ).dropna()
    daily_gaps = (daily_gaps["nav"] - daily_gaps["index"]).tail(window)
    if len(daily_gaps) < min(minimum_aligned_days, window):
        return None
    return float(daily_gaps.std(ddof=1) * np.sqrt(trading_days))
