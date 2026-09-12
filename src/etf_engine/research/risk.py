import pandas as pd


def current_drawdown(series: pd.Series) -> float | None:
    clean = series.dropna().astype(float)
    if clean.empty:
        return None
    peak = clean.cummax()
    dd = clean / peak - 1.0
    return float(dd.iloc[-1])


def max_drawdown(series: pd.Series, window: int | None = None) -> float | None:
    clean = series.dropna().astype(float)
    if window:
        if len(clean) < window:
            return None
        clean = clean.tail(window)
    if clean.empty:
        return None
    peak = clean.cummax()
    dd = clean / peak - 1.0
    return float(dd.min())
