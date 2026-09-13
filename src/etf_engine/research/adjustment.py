"""复权序列（``adjust_v1``）。

口径是**后复权**：``adjusted = 原始值 × U(t)``，其中 ``U(t)`` 只累积
**截至 t（含）** 的公司行为。

为什么不用前复权：前复权要用"未来还会发生的拆分"去改历史值。在图表里无妨，
但在研究里等于把当时还不知道的信息灌回历史——正是
``adjusted_series_future_action_leak`` 要拦的事。后复权天然 Point-in-Time 安全：
任一历史行只依赖它自己和它之前的事实。

因子累积规则（``U`` 的更新，均发生在行为日当天）：

```text
拆分/折算   shares ×k, nav ÷k   →  U ← U × k          （保证 P×U 连续）
分红        除息日价格掉 d      →  U ← U × P_prev / (P_prev - d)
```

**生效日对齐**（实测确认，不是猜的）：

```text
单位净值 / 份额   折算日 T 当日就是折算后的值（基金层面的日终事实）
成交价            折算日 T 仍是折算前价格，T+1 个交易日才按新份额交易
```

515880.SH 实测：净值 2026-07-02 的 1.5774 到 07-03 变 0.7885；
而价格 07-03 仍是 1.579，到 07-06 才是 0.757。两套序列必须各按自己的
生效日对齐，否则会给其中一套制造出假的 ±100% 跳变。

分红的 P_prev 取除息日前最后一个收盘价（只用历史数据，不回看未来）。
缺少可用的 P_prev 或 d >= P_prev 时，该次分红不参与复权并记问题——
宁可复权序列保守，也不要造出一个假的连续性。
"""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from etf_engine.domain.enums import CorporateActionType
from etf_engine.domain.models import AdjustedDailyPoint, ETFCorporateAction
from etf_engine.domain.quality import DataQualityIssue, warn

#: 复权口径版本。因子累积规则或分红处理方式变化时必须升级。
ADJUSTMENT_VERSION = "adjust_v1"


@dataclass(frozen=True, slots=True)
class AdjustmentInputs:
    """构建复权序列所需的事实（都是未复权的原始值）。"""

    security_id: str
    #: ``(trade_date, close)``，按日期升序
    closes: list[tuple[date, Decimal | None]]
    #: ``(trade_date, unit_nav)``，按日期升序
    navs: list[tuple[date, Decimal | None]]
    #: ``(trade_date, shares)``，按日期升序
    shares: list[tuple[date, Decimal | None]]
    actions: list[ETFCorporateAction]


def _previous_close(closes: list[tuple[date, Decimal | None]], before: date) -> Decimal | None:
    previous: Decimal | None = None
    for trade_date, close in closes:
        if trade_date >= before:
            break
        if close is not None:
            previous = close
    return previous


def _first_date_strictly_after(dates: list[date], value: date) -> date | None:
    for candidate in dates:
        if candidate > value:
            return candidate
    return None


def _first_date_on_or_after(dates: list[date], value: date) -> date | None:
    for candidate in dates:
        if candidate >= value:
            return candidate
    return None


def build_adjusted_series(
    inputs: AdjustmentInputs,
) -> tuple[list[AdjustedDailyPoint], list[DataQualityIssue]]:
    """按日构建复权序列。"""
    issues: list[DataQualityIssue] = []
    actions_by_date: dict[date, list[ETFCorporateAction]] = {}
    for action in inputs.actions:
        actions_by_date.setdefault(action.action_date, []).append(action)

    close_dates = [trade_date for trade_date, _ in inputs.closes]
    nav_dates = [trade_date for trade_date, _ in inputs.navs]
    share_dates = [trade_date for trade_date, _ in inputs.shares]
    closes = dict(inputs.closes)
    navs = dict(inputs.navs)
    shares = dict(inputs.shares)
    timeline = sorted({*closes, *navs, *shares})

    # 每套序列各自的生效日：净值/份额当日生效，价格次一交易日生效。
    close_effects: dict[date, list[ETFCorporateAction]] = {}
    fact_effects: dict[date, list[ETFCorporateAction]] = {}
    for action in inputs.actions:
        price_date = _first_date_strictly_after(close_dates, action.action_date)
        if price_date is not None:
            close_effects.setdefault(price_date, []).append(action)
        fact_date = _first_date_on_or_after(sorted({*nav_dates, *share_dates}), action.action_date)
        if fact_date is not None:
            fact_effects.setdefault(fact_date, []).append(action)

    close_factor = Decimal(1)
    fact_factor = Decimal(1)
    points: list[AdjustedDailyPoint] = []

    for trade_date in timeline:
        for action in close_effects.get(trade_date, []):
            close_factor = _apply_action_factor(
                action,
                factor=close_factor,
                inputs=inputs,
                trade_date=trade_date,
                issues=issues,
            )
        for action in fact_effects.get(trade_date, []):
            fact_factor = _apply_action_factor(
                action,
                factor=fact_factor,
                inputs=inputs,
                trade_date=trade_date,
                issues=issues,
            )

        close = closes.get(trade_date)
        nav = navs.get(trade_date)
        share = shares.get(trade_date)
        points.append(
            AdjustedDailyPoint(
                security_id=inputs.security_id,
                trade_date=trade_date,
                adjusted_close=(close * close_factor) if close is not None else None,
                adjusted_nav=(nav * fact_factor) if nav is not None else None,
                adjusted_shares=(share / fact_factor) if share is not None else None,
                adjustment_factor=fact_factor,
                price_adjustment_factor=close_factor,
            )
        )

    return points, issues


def _apply_action_factor(
    action: ETFCorporateAction,
    *,
    factor: Decimal,
    inputs: AdjustmentInputs,
    trade_date: date,
    issues: list[DataQualityIssue],
) -> Decimal:
    """把一次公司行为累积到因子上（无效行为只记问题，不改变因子）。"""
    if action.action_type is CorporateActionType.DIVIDEND:
        previous_close = _previous_close(inputs.closes, min(trade_date, action.action_date))
        cash = action.cash_distribution
        if previous_close is None or cash is None or cash <= 0:
            issues.append(
                warn(
                    "dividend_adjustment_skipped",
                    f"{inputs.security_id} {action.action_date} 缺少可用前收盘或派现额，"
                    "该次分红不参与复权",
                )
            )
            return factor
        if cash >= previous_close:
            issues.append(
                warn(
                    "dividend_exceeds_price",
                    f"{inputs.security_id} {action.action_date} 每份派现 {cash} >= "
                    f"前收盘 {previous_close}，该次分红不参与复权",
                )
            )
            return factor
        return factor * previous_close / (previous_close - cash)

    share_factor = action.share_adjustment_factor
    if share_factor is None or share_factor <= 0:
        issues.append(
            warn(
                "split_adjustment_skipped",
                f"{inputs.security_id} {action.action_date} 拆分比例缺失，不参与复权",
            )
        )
        return factor
    return factor * share_factor


def share_factor_on(actions: list[ETFCorporateAction], trade_date: date) -> Decimal:
    """某一天的机械份额倍数（无行为时为 1）。

    资金流口径用它剔除"折算造成的份额跳变"——那是机械变化，不是申赎。
    """
    factor = Decimal(1)
    for action in actions:
        if action.action_date != trade_date:
            continue
        if action.action_type is CorporateActionType.DIVIDEND:
            continue
        if action.share_adjustment_factor is not None and action.share_adjustment_factor > 0:
            factor *= action.share_adjustment_factor
    return factor
