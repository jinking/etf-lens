"""Historical Regime Validation（历史 regime 验证，不做阈值寻优）。

它回答的问题只有一类：

```text
把已经固定的状态规则（pulse_v2）放回历史里，它长什么样？
```

* 覆盖与稳定性：每个 regime 覆盖多少天、UNKNOWN 占多少、切换多少次、平均持续多久；
* 后续分布：某个状态出现之后 5/20/60 个交易日的收益分布、最大回撤分布。

**它不回答**"哪套阈值历史收益最好"。为了让历史收益更好而自动调阈值被明确排除
（升级方案 §15.2），阈值属于 :mod:`etf_engine.research.market_pulse` 的规则常量，
改动必须升版本号。

两个必须区分的能力边界（升级方案 §16–19）：

1. **regime 定义预先固定**：这里只用"自然年"做时间切片，不根据未来结果反向划段；
2. **样本独立性**：同一段连续状态里的每一天高度重叠，因此每个
   ``(状态, 窗口)`` 同时给出两套样本——

   - ``daily``：每天都算一个样本（分布统计，样本不独立）；
   - ``transition``：只取"进入该状态的那一天"（首日 + 每次切换当天），
     避免连续 20 天"偏多"被当成 20 个独立样本。

本模块是纯统计：输入相同必然输出相同，不做 I/O、不读数据库。
"""

from dataclasses import dataclass, field
from datetime import date
from statistics import median

import pandas as pd

#: 后续收益观察窗口（交易日）。
FORWARD_WINDOWS: tuple[int, ...] = (5, 20, 60)

#: 样本口径：``daily`` = 每天一个样本；``transition`` = 状态首次进入当天。
SAMPLE_DAILY = "daily"
SAMPLE_TRANSITION = "transition"

#: regime 切分口径（预先固定，不看结果）。当前只按自然年切。
REGIME_DEFINITION = "按自然年（calendar-year）预先切分，不根据未来收益反向划段"


@dataclass(frozen=True, slots=True)
class StateSummary:
    state: str
    days: int
    share: float
    average_duration: float | None
    median_duration: float | None


@dataclass(frozen=True, slots=True)
class ForwardStats:
    """某一 ``(状态, 窗口, 样本口径)`` 下的分布统计。"""

    sample_count: int
    return_mean: float | None
    return_median: float | None
    return_p10: float | None
    return_p90: float | None
    max_drawdown_mean: float | None
    max_drawdown_worst: float | None


def _empty_stats() -> ForwardStats:
    return ForwardStats(0, None, None, None, None, None, None)


@dataclass(frozen=True, slots=True)
class ForwardOutcome:
    """一个状态在一个观察窗口下的两套样本统计。

    ``daily`` 与 ``transition`` 用同一批交易日的收盘价计算，区别只在起点集合：
    前者是"出现该状态的每一天"，后者是"进入该状态的当天"。
    """

    state: str
    window: int
    daily: ForwardStats
    transition: ForwardStats

    @property
    def sample_size(self) -> int:
        """兼容旧字段名：等于 daily 样本数。"""
        return self.daily.sample_count


@dataclass(frozen=True, slots=True)
class RegimeSlice:
    """一个 regime（当前 = 一个自然年）的完整统计。"""

    label: str
    days: int
    unknown_ratio: float
    switch_count: int
    states: list[StateSummary] = field(default_factory=list)
    outcomes: list[ForwardOutcome] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class RegimeValidationReport:
    days: int
    unknown_ratio: float
    switch_count: int
    states: list[StateSummary] = field(default_factory=list)
    outcomes: list[ForwardOutcome] = field(default_factory=list)
    regimes: list[RegimeSlice] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def state_durations(states: list[str]) -> dict[str, list[int]]:
    """每种状态的连续持续天数（按出现顺序切段）。"""
    durations: dict[str, list[int]] = {}
    if not states:
        return durations
    current = states[0]
    length = 1
    for state in states[1:]:
        if state == current:
            length += 1
        else:
            durations.setdefault(current, []).append(length)
            current, length = state, 1
    durations.setdefault(current, []).append(length)
    return durations


def state_entries(states: list[str]) -> list[int]:
    """进入某状态的下标：序列首日 + 每次状态切换当天。

    这是 ``transition`` 样本口径的起点集合：同一段连续状态只贡献 1 个样本，
    因此"连续 20 天偏多"不会被算成 20 个独立事件。
    """
    if not states:
        return []
    entries = [0]
    for position in range(1, len(states)):
        if states[position] != states[position - 1]:
            entries.append(position)
    return entries


def state_summary(states: list[str]) -> list[StateSummary]:
    total = len(states)
    if total == 0:
        return []
    durations = state_durations(states)
    summaries: list[StateSummary] = []
    order = {state: index for index, state in enumerate(dict.fromkeys(states))}
    for state in sorted(set(states), key=lambda item: order[item]):
        days = states.count(state)
        runs = durations.get(state, [])
        summaries.append(
            StateSummary(
                state=state,
                days=days,
                share=days / total,
                average_duration=(sum(runs) / len(runs)) if runs else None,
                median_duration=float(median(runs)) if runs else None,
            )
        )
    return summaries


def switch_count(states: list[str]) -> int:
    """状态切换次数（相邻两天不同即算一次切换）。"""
    return sum(1 for left, right in zip(states, states[1:], strict=False) if left != right)


def _forward_stats(
    *,
    states: list[str],
    values: pd.Series,
    state: str,
    window: int,
    positions: list[int],
    unknown_state: str,
) -> ForwardStats:
    """在给定起点集合上统计某状态的后续收益与回撤。

    观察窗口可以跨出该 regime 的边界（例如 12 月 30 日之后可以看到次年 1 月），
    否则每年最后 ``window`` 天的样本会被系统性丢掉。样本不足的窗口
    （观察期落在序列末尾之外，或起点值缺失 / <= 0）不计入，不做前向填充。
    """
    returns: list[float] = []
    drawdowns: list[float] = []
    size = len(values)
    for position in positions:
        if position >= len(states) or states[position] != state or state == unknown_state:
            continue
        end = position + window
        if end >= size:
            continue
        start_value = values.iloc[position]
        if start_value is None or start_value != start_value or start_value <= 0:
            continue
        forward = values.iloc[position + 1 : end + 1].dropna()
        if forward.empty:
            continue
        returns.append(float(forward.iloc[-1] / start_value - 1))
        drawdowns.append(float(forward.min() / start_value - 1))

    if not returns:
        return _empty_stats()
    series = pd.Series(returns)
    return ForwardStats(
        sample_count=len(returns),
        return_mean=float(series.mean()),
        return_median=float(series.median()),
        return_p10=float(series.quantile(0.1)),
        return_p90=float(series.quantile(0.9)),
        max_drawdown_mean=float(pd.Series(drawdowns).mean()),
        max_drawdown_worst=float(pd.Series(drawdowns).min()),
    )


def forward_outcomes(
    *,
    states: list[str],
    index_close: pd.Series,
    unknown_state: str = "UNKNOWN",
    daily_positions: list[int] | None = None,
    transition_positions: list[int] | None = None,
) -> list[ForwardOutcome]:
    """每个状态之后 N 日的收益与回撤分布，同时给出 daily / transition 两套样本。

    ``daily_positions`` / ``transition_positions`` 分别限定两套样本的起点集合
    （用于按 regime 切片）；缺省时 daily 取全部交易日、transition 取
    :func:`state_entries`。``states`` 与 ``index_close`` 按同一交易日序列对齐。
    """
    if not states or index_close.empty:
        return []
    values = pd.to_numeric(index_close, errors="coerce")
    daily = list(range(len(states))) if daily_positions is None else daily_positions
    transition = state_entries(states) if transition_positions is None else transition_positions

    outcomes: list[ForwardOutcome] = []
    for state in sorted(set(states)):
        for window in FORWARD_WINDOWS:
            outcomes.append(
                ForwardOutcome(
                    state=state,
                    window=window,
                    daily=_forward_stats(
                        states=states,
                        values=values,
                        state=state,
                        window=window,
                        positions=daily,
                        unknown_state=unknown_state,
                    ),
                    transition=_forward_stats(
                        states=states,
                        values=values,
                        state=state,
                        window=window,
                        positions=transition,
                        unknown_state=unknown_state,
                    ),
                )
            )
    return outcomes


def _unknown_ratio(states: list[str], unknown_state: str) -> float:
    if not states:
        return 0.0
    return states.count(unknown_state) / len(states)


def build_regime_slices(
    *,
    states: list[str],
    index_close: pd.Series,
    dates: list[date],
    unknown_state: str = "UNKNOWN",
) -> list[RegimeSlice]:
    """按预先固定的 regime 定义（自然年）切片，逐段给出完整统计。"""
    if not states or not dates:
        return []
    entries = state_entries(states)
    slices: list[RegimeSlice] = []
    for year in sorted({day.year for day in dates}):
        year_positions = [index for index, day in enumerate(dates) if day.year == year]
        year_states = [states[index] for index in year_positions]
        year_entries = [index for index in entries if dates[index].year == year]
        slices.append(
            RegimeSlice(
                label=str(year),
                days=len(year_positions),
                unknown_ratio=_unknown_ratio(year_states, unknown_state),
                switch_count=switch_count(year_states),
                states=state_summary(year_states),
                outcomes=forward_outcomes(
                    states=states,
                    index_close=index_close,
                    unknown_state=unknown_state,
                    daily_positions=year_positions,
                    transition_positions=year_entries,
                ),
            )
        )
    return slices


def build_report(
    *,
    states: list[str],
    index_close: pd.Series,
    unknown_state: str = "UNKNOWN",
    dates: list[date] | None = None,
    notes: list[str] | None = None,
) -> RegimeValidationReport:
    return RegimeValidationReport(
        days=len(states),
        unknown_ratio=_unknown_ratio(states, unknown_state),
        switch_count=switch_count(states),
        states=state_summary(states),
        outcomes=forward_outcomes(
            states=states, index_close=index_close, unknown_state=unknown_state
        ),
        regimes=(
            build_regime_slices(
                states=states,
                index_close=index_close,
                dates=dates,
                unknown_state=unknown_state,
            )
            if dates
            else []
        ),
        notes=notes or [],
    )


def _state_table(states: list[StateSummary]) -> list[str]:
    lines = [
        "| 状态 | 天数 | 占比 | 平均持续 | 中位持续 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for row in states:
        average = "—" if row.average_duration is None else f"{row.average_duration:.1f}"
        med = "—" if row.median_duration is None else f"{row.median_duration:.1f}"
        lines.append(f"| {row.state} | {row.days} | {row.share:.1%} | {average} | {med} |")
    return lines


def _outcome_table(outcomes: list[ForwardOutcome], mode: str) -> list[str]:
    if mode == SAMPLE_TRANSITION:
        header = (
            "| 状态 | 窗口 | transition 样本 | 收益均值 | 收益中位 | 回撤均值 | 最深回撤 |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        )
    else:
        header = (
            "| 状态 | 窗口 | daily 样本 | 收益均值 | 收益中位 | 收益 p10 | 收益 p90 "
            "| 回撤均值 | 最深回撤 |",
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
        )
    lines = [header[0], header[1]]
    for outcome in outcomes:
        stats = outcome.transition if mode == SAMPLE_TRANSITION else outcome.daily
        if stats.sample_count == 0:
            # 列数 = 表头总数 - 3（状态 / 窗口 / 样本）
            blanks = 4 if mode == SAMPLE_TRANSITION else 6
            cells = " | ".join(["—"] * blanks)
            lines.append(f"| {outcome.state} | {outcome.window}日 | 0 | {cells} |")
            continue
        if mode == SAMPLE_TRANSITION:
            lines.append(
                f"| {outcome.state} | {outcome.window}日 | {stats.sample_count} "
                f"| {stats.return_mean:+.2%} | {stats.return_median:+.2%} "
                f"| {stats.max_drawdown_mean:+.2%} | {stats.max_drawdown_worst:+.2%} |"
            )
        else:
            lines.append(
                f"| {outcome.state} | {outcome.window}日 | {stats.sample_count} "
                f"| {stats.return_mean:+.2%} | {stats.return_median:+.2%} "
                f"| {stats.return_p10:+.2%} | {stats.return_p90:+.2%} "
                f"| {stats.max_drawdown_mean:+.2%} | {stats.max_drawdown_worst:+.2%} |"
            )
    return lines


def render_markdown(report: RegimeValidationReport, *, title: str, context: list[str]) -> str:
    """把报告渲染成 Markdown。只描述统计事实，不写"必涨/胜率保证"。"""
    lines = [f"# {title}", "", *context, ""]

    lines += [
        "## 1. 覆盖与稳定性",
        "",
        f"- 覆盖交易日：**{report.days}**",
        f"- UNKNOWN 占比：**{report.unknown_ratio:.1%}**",
        f"- 状态切换次数：**{report.switch_count}**"
        + (
            f"（平均每 {report.days / report.switch_count:.1f} 个交易日切换一次）"
            if report.switch_count
            else ""
        ),
        "",
        *_state_table(report.states),
        "",
        "## 2. 状态之后的收益与回撤分布（daily 样本）",
        "",
        "单位为百分比；`daily` 样本 = 出现该状态的每一个交易日（样本高度重叠，只作分布描述）。",
        "",
        *_outcome_table(report.outcomes, SAMPLE_DAILY),
        "",
        "## 3. 状态之后的收益与回撤分布（transition 样本）",
        "",
        "`transition` 样本 = 状态首次进入的那一天（序列首日 + 每次切换当天），"
        "同一段连续状态只贡献 1 个样本，避免把高度重叠的日子当成独立事件。",
        "",
        *_outcome_table(report.outcomes, SAMPLE_TRANSITION),
    ]

    if report.regimes:
        lines += [
            "",
            "## 4. 分 regime 视图",
            "",
            f"regime 定义：{REGIME_DEFINITION}。",
            "",
            "| regime | 交易日 | 切换次数 | UNKNOWN 占比 | 平均持续 |",
            "| --- | --- | --- | --- | --- |",
        ]
        for regime in report.regimes:
            durations = [row.average_duration for row in regime.states if row.average_duration]
            average = "—" if not durations else f"{sum(durations) / len(durations):.1f}"
            lines.append(
                f"| {regime.label} | {regime.days} | {regime.switch_count} "
                f"| {regime.unknown_ratio:.1%} | {average} |"
            )
        for regime in report.regimes:
            lines += [
                "",
                f"### {regime.label}",
                "",
                "状态分布：",
                "",
                *_state_table(regime.states),
                "",
                "状态之后的收益与回撤（daily 样本）：",
                "",
                *_outcome_table(regime.outcomes, SAMPLE_DAILY),
                "",
                "状态之后的收益与回撤（transition 样本）：",
                "",
                *_outcome_table(regime.outcomes, SAMPLE_TRANSITION),
            ]

    if report.notes:
        lines += ["", "## 5. 说明与边界", ""]
        lines += [f"- {note}" for note in report.notes]
    lines += [
        "",
        "---",
        "",
        "本文只描述统计事实，不含任何“必涨”“胜率保证”之类的结论；",
        "阈值优化被明确排除在 V2 范围之外（见 `docs/WATCHBOARD.md` 与升级方案 §15.2）。",
        "",
    ]
    return "\n".join(lines)
