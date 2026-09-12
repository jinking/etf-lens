from dataclasses import dataclass

import pandas as pd


@dataclass(slots=True)
class FlowMetrics:
    share_change_1d: float | None
    share_change_pct_1d: float | None
    share_change_5d: float | None
    share_change_20d: float | None
    share_change_60d: float | None
    estimated_net_subscription_1d: float | None
    estimated_net_subscription_2d: float | None
    estimated_net_subscription_5d: float | None
    estimated_net_subscription_20d: float | None
    estimated_net_subscription_60d: float | None
    consecutive_share_inflow_days: int
    consecutive_share_outflow_days: int


def _change(series: pd.Series, periods: int) -> float | None:
    values = pd.to_numeric(series, errors="coerce").tail(periods + 1)
    if len(values) < periods + 1 or values.isna().any():
        return None
    return float(values.iloc[-1] - values.iloc[0])


def share_change_pct(series: pd.Series, periods: int) -> float | None:
    values = pd.to_numeric(series, errors="coerce").tail(periods + 1)
    if len(values) < periods + 1 or values.isna().any() or values.iloc[0] == 0:
        return None
    return float(values.iloc[-1] / values.iloc[0] - 1.0)


def _estimated_subscription(shares: pd.Series, nav: pd.Series | None, periods: int) -> float | None:
    if nav is None:
        return None
    share_values = pd.to_numeric(shares, errors="coerce").tail(periods + 1)
    nav_values = pd.to_numeric(nav, errors="coerce").reindex(share_values.index).tail(periods)
    if (
        len(share_values) < periods + 1
        or len(nav_values) < periods
        or share_values.isna().any()
        or nav_values.isna().any()
    ):
        return None
    return float((share_values.diff().iloc[1:] * nav_values).sum())


def calculate_flow(shares: pd.Series, nav: pd.Series | None = None) -> FlowMetrics:
    clean = pd.to_numeric(shares, errors="coerce")

    c1 = _change(clean, 1)
    c5 = _change(clean, 5)
    c20 = _change(clean, 20)
    c60 = _change(clean, 60)

    pct1 = share_change_pct(clean, 1)

    est1 = _estimated_subscription(clean, nav, 1)

    inflow = 0
    outflow = 0
    if len(clean) >= 2:
        diffs = clean.diff().dropna().iloc[::-1]
        for value in diffs:
            if value > 0:
                if outflow:
                    break
                inflow += 1
            elif value < 0:
                if inflow:
                    break
                outflow += 1
            else:
                break

    return FlowMetrics(
        share_change_1d=c1,
        share_change_pct_1d=pct1,
        share_change_5d=c5,
        share_change_20d=c20,
        share_change_60d=c60,
        estimated_net_subscription_1d=est1,
        estimated_net_subscription_2d=_estimated_subscription(clean, nav, 2),
        estimated_net_subscription_5d=_estimated_subscription(clean, nav, 5),
        estimated_net_subscription_20d=_estimated_subscription(clean, nav, 20),
        estimated_net_subscription_60d=_estimated_subscription(clean, nav, 60),
        consecutive_share_inflow_days=inflow,
        consecutive_share_outflow_days=outflow,
    )
