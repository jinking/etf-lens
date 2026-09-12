import numpy as np
import pandas as pd


def simple_return(series: pd.Series, periods: int) -> float | None:
    values = pd.to_numeric(series, errors="coerce").tail(periods + 1)
    if len(values) < periods + 1 or values.isna().any():
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
    returns = np.log(clean / clean.shift(1)).dropna().tail(window)
    if len(returns) < window:
        return None
    return float(returns.std(ddof=1) * np.sqrt(trading_days))
