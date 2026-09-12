"""未复权序列的除权/折算检测。

份额折算、拆分、分红会让单位净值和成交价出现机械跳变。当前落库的是**未复权**
价格与单位净值（``core.etf_quote_daily.close``、``core.etf_nav_daily.unit_nav``），
所以任何跨过除权日的收益率、波动率、回撤、跟踪误差都是错的。

实测例子：515880.SH 在 2026-07-03 做了一次 2:1 份额折算，当日单位净值从 1.5774
跌到 0.7885（-50%），而同期指数只跌约 5%。不做判断地计算跟踪误差会得到 100%。

本模块只做"能不能用"的判断，不做复权——复权净值应作为独立字段另行采集。
"""

import pandas as pd

#: 单日跳变超过该幅度即认为该区间包含未复权的公司行为。
#: A 股 ETF 单日涨跌幅有 10%（部分 20%）限制，20% 足以区分真实行情与机械跳变。
DEFAULT_JUMP_THRESHOLD = 0.20


def has_unadjusted_jump(
    series: pd.Series | None,
    *,
    threshold: float = DEFAULT_JUMP_THRESHOLD,
) -> bool:
    """序列中是否存在未复权的机械跳变。"""
    if series is None:
        return False
    clean = pd.to_numeric(series, errors="coerce").dropna()
    if len(clean) < 2:
        return False
    returns = clean.pct_change().dropna()
    if returns.empty:
        return False
    return bool((returns.abs() > threshold).any())


def has_unadjusted_jump_in_window(
    series: pd.Series | None,
    *,
    periods: int,
    threshold: float = DEFAULT_JUMP_THRESHOLD,
) -> bool:
    """只看窗口内（最近 periods+1 个观测）是否存在跳变。"""
    if series is None:
        return False
    clean = pd.to_numeric(series, errors="coerce").dropna().tail(periods + 1)
    return has_unadjusted_jump(clean, threshold=threshold)
