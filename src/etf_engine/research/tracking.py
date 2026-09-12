import numpy as np
import pandas as pd

from etf_engine.research.corporate_actions import has_unadjusted_jump


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
