import pandas as pd


def normalize_premium_discount(close: float | None, iopv: float | None) -> float | None:
    """Return a premium as a positive value and a discount as a negative value."""
    if close is None or iopv is None or iopv <= 0:
        return None
    return (float(close) - float(iopv)) / float(iopv)


def average_turnover_amount(turnover_amount: pd.Series, window: int) -> float | None:
    values = pd.to_numeric(turnover_amount, errors="coerce").tail(window)
    if len(values) < window or values.isna().any():
        return None
    return float(values.mean())


def bid_ask_spread(bid1: float | None, ask1: float | None) -> tuple[float, float] | None:
    if bid1 is None or ask1 is None or bid1 <= 0 or ask1 <= 0 or ask1 < bid1:
        return None
    mid_price = (float(bid1) + float(ask1)) / 2
    if mid_price <= 0:
        return None
    spread = float(ask1) - float(bid1)
    return spread, spread / mid_price
