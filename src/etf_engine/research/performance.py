import numpy as np
import pandas as pd

from etf_engine.research.corporate_actions import has_unadjusted_jump_in_window


def simple_return(series: pd.Series, periods: int) -> float | None:
    values = pd.to_numeric(series, errors="coerce").tail(periods + 1)
    if len(values) < periods + 1 or values.isna().any():
        return None
    if has_unadjusted_jump_in_window(values, periods=periods):
        # 未复权序列跨过除权/折算日时，收益率不是真实收益。
        return None
    start = float(values.iloc[0])
    end = float(values.iloc[-1])
    if start == 0:
        return None
    return end / start - 1.0


def annualized_volatility(series: pd.Series, window: int, trading_days: int = 242) -> float | None:
    clean = series.dropna().astype(float)
    if len(clean) <= window:
        return None
    if has_unadjusted_jump_in_window(clean.tail(window + 1), periods=window):
        return None
    returns = np.log(clean / clean.shift(1)).dropna().tail(window)
    if len(returns) < window:
        return None
    return float(returns.std(ddof=1) * np.sqrt(trading_days))
