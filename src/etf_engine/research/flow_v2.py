"""公司行为感知的资金流口径（``flow_v2``）。

``flow_v1`` 用 ``Δshares × NAV`` 估算申赎。份额拆分/折算当天，份额会出现
机械跳变（1:2 分拆 → 份额翻倍），v1 会把它误判成一笔巨额申购。

v2 的做法：先把机械放大扣掉，再乘当日净值：

```text
真实份额变化 = shares(t) − shares(t−1) × k(t)      k(t) = 当日机械倍数（无行为时 1）
估算净申购   = 真实份额变化 × NAV(t)
```

同一只 ETF 在没有公司行为的区间里，v1 与 v2 结果完全相同——v2 只修正被
折算污染的那部分。
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from etf_engine.domain.models import ETFCorporateAction
from etf_engine.research.adjustment import share_factor_on

FLOW_QUALITY_CLEAN = "clean"
FLOW_QUALITY_ADJUSTED = "corporate_action_adjusted"


@dataclass(frozen=True, slots=True)
class CorporateActionAwareChange:
    """一次份额变化：机械部分与经济部分分开。"""

    mechanical_change: Decimal | None
    economic_change: Decimal | None
    share_factor: Decimal
    quality_status: str


def adjusted_share_change(
    *,
    shares_prev: Decimal | None,
    shares_now: Decimal | None,
    trade_date: date,
    actions: list[ETFCorporateAction],
) -> CorporateActionAwareChange:
    """把某一天的份额变化拆成"机械"与"经济"两部分。"""
    if shares_prev is None or shares_now is None:
        return CorporateActionAwareChange(None, None, Decimal(1), FLOW_QUALITY_CLEAN)

    factor = share_factor_on(actions, trade_date)
    mechanical = (shares_prev * (factor - 1)) if factor != 1 else Decimal(0)
    economic = shares_now - shares_prev * factor
    quality = FLOW_QUALITY_ADJUSTED if factor != 1 else FLOW_QUALITY_CLEAN
    return CorporateActionAwareChange(mechanical, economic, factor, quality)


def estimated_subscription_v2(
    *,
    shares_prev: Decimal | None,
    shares_now: Decimal | None,
    nav_now: Decimal | None,
    trade_date: date,
    actions: list[ETFCorporateAction],
) -> tuple[Decimal | None, str]:
    """单日估算净申购（v2）+ 质量标记。"""
    change = adjusted_share_change(
        shares_prev=shares_prev,
        shares_now=shares_now,
        trade_date=trade_date,
        actions=actions,
    )
    if change.economic_change is None or nav_now is None:
        return None, change.quality_status
    return change.economic_change * nav_now, change.quality_status


#: 资金流窗口（交易日）。
WINDOWS = (1, 5, 20, 60)


def flow_v2_windows(adjusted) -> tuple[dict, str]:
    """基于复权序列计算各窗口的资金流指标。

    输入是 ``mart.etf_adjusted_daily`` 的 DataFrame（``adjusted_shares`` /
    ``adjusted_nav`` / ``adjustment_factor``，按日期升序）。所有口径都建立在
    复权序列上，因此折算造成的机械份额变化自动被剔除：

    ```text
    经济份额变化（最新时点单位）= Δadjusted_shares × U(最新)
    估算净申购（元）           = Σ Δadjusted_shares × adjusted_nav
    ```

    ``adjusted_nav`` 缺失的日期不参与金额求和；窗口内净值不全时返回 NULL，
    不降级用别的价格顶替。
    """
    import pandas as pd  # 局部导入：本模块的纯函数不依赖 pandas 之外的重物

    shares = pd.to_numeric(adjusted["adjusted_shares"], errors="coerce")
    nav = pd.to_numeric(adjusted["adjusted_nav"], errors="coerce")
    factor = pd.to_numeric(adjusted["adjustment_factor"], errors="coerce")

    latest_factor = float(factor.iloc[-1]) if len(factor) and pd.notna(factor.iloc[-1]) else 1.0
    base_change = shares.diff()
    money_base = base_change * nav

    metrics: dict = {}
    for window in WINDOWS:
        base_window = base_change.tail(window)
        if len(base_window) < window or base_window.isna().any():
            share_change = None
        else:
            share_change = float(base_window.sum()) * latest_factor

        money_window = money_base.tail(window)
        if len(money_window) < window or money_window.isna().any():
            subscription = None
        else:
            subscription = float(money_window.sum())

        metrics[f"share_change_{window}d"] = share_change
        metrics[f"estimated_{window}d"] = subscription

        if window == 1:
            metrics["share_change_pct_1d"] = _pct(share_change, shares, latest_factor, window)
        else:
            metrics[f"share_change_pct_{window}d"] = _pct(
                share_change, shares, latest_factor, window
            )

    inflow, outflow = _streak(base_change)
    metrics["inflow_days"] = inflow
    metrics["outflow_days"] = outflow

    adjusted = bool(len(factor) > 1 and factor.nunique(dropna=True) > 1)
    quality = FLOW_QUALITY_ADJUSTED if adjusted else FLOW_QUALITY_CLEAN
    return metrics, quality


def _pct(share_change: float | None, shares, latest_factor: float, window: int):
    if share_change is None:
        return None
    base_value = shares.shift(window).iloc[-1]
    if base_value is None or base_value != base_value or base_value == 0:
        return None
    base_in_current_units = float(base_value) * latest_factor
    if base_in_current_units == 0:
        return None
    return share_change / base_in_current_units


def _streak(base_change) -> tuple[int, int]:
    """连续流入/流出天数（基于复权后的经济变化，方向由此确定）。"""
    values = [value for value in base_change.dropna().tolist()[::-1]]
    inflow = outflow = 0
    for value in values:
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
    return inflow, outflow
