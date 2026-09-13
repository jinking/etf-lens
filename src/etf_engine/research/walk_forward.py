"""规则稳定性验证（walk-forward，不做寻优）。

只回答四类问题：

```text
状态分布        各状态占多少天、UNKNOWN 占多少
状态持续时间    平均 / 中位持续天数
切换频率        切换次数与每次平均持续
后续分布        每个状态之后 5/20/60 日的收益分布、最大回撤分布
```

**明确不做**：为了让历史收益更好而自动调整阈值。这里的函数都是纯统计，
输入相同必然输出相同；阈值属于 :mod:`etf_engine.research.market_pulse`
（``pulse_v2``）的规则常量，改动必须升版本号，且不在本模块里做。
"""

from dataclasses import dataclass, field
from statistics import median

import pandas as pd

#: 后续收益观察窗口（交易日）。
FORWARD_WINDOWS: tuple[int, ...] = (5, 20, 60)


@dataclass(frozen=True, slots=True)
class StateSummary:
    state: str
    days: int
    share: float
    average_duration: float | None
    median_duration: float | None


@dataclass(frozen=True, slots=True)
class ForwardOutcome:
    state: str
    window: int
    sample_size: int
    return_mean: float | None
    return_median: float | None
    return_p10: float | None
    return_p90: float | None
    max_drawdown_mean: float | None
    max_drawdown_worst: float | None


@dataclass(frozen=True, slots=True)
class WalkForwardReport:
    days: int
    unknown_ratio: float
    switch_count: int
    states: list[StateSummary] = field(default_factory=list)
    outcomes: list[ForwardOutcome] = field(default_factory=list)
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


def state_summary(states: list[str]) -> list[StateSummary]:
    total = len(states)
    if total == 0:
        return []
    durations = state_durations(states)
    summaries: list[StateSummary] = []
    for state in sorted(set(states)):
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


def forward_outcomes(
    *,
    states: list[str],
    index_close: pd.Series,
    unknown_state: str = "UNKNOWN",
) -> list[ForwardOutcome]:
    """每个状态之后 N 日的收益与回撤分布。

    ``states`` 与 ``index_close`` 按同一交易日序列对齐；样本不足的窗口
    （观察期落在序列末尾之外，或起点值为 0）不计入，不做前向填充。
    """
    if not states or index_close.empty:
        return []
    values = pd.to_numeric(index_close, errors="coerce")
    outcomes: list[ForwardOutcome] = []

    for state in sorted(set(states)):
        for window in FORWARD_WINDOWS:
            returns: list[float] = []
            drawdowns: list[float] = []
            for position, current in enumerate(states):
                if current != state or current == unknown_state:
                    continue
                end = position + window
                if end >= len(values):
                    continue
                start_value = values.iloc[position]
                if start_value is None or start_value != start_value or start_value <= 0:
                    continue
                forward = values.iloc[position + 1 : end + 1].dropna()
                if forward.empty:
                    continue
                returns.append(float(forward.iloc[-1] / start_value - 1))
                trough = forward.min()
                drawdowns.append(float(trough / start_value - 1))

            if not returns:
                outcomes.append(
                    ForwardOutcome(state, window, 0, None, None, None, None, None, None)
                )
                continue
            series = pd.Series(returns)
            outcomes.append(
                ForwardOutcome(
                    state=state,
                    window=window,
                    sample_size=len(returns),
                    return_mean=float(series.mean()),
                    return_median=float(series.median()),
                    return_p10=float(series.quantile(0.1)),
                    return_p90=float(series.quantile(0.9)),
                    max_drawdown_mean=float(pd.Series(drawdowns).mean()),
                    max_drawdown_worst=float(pd.Series(drawdowns).min()),
                )
            )
    return outcomes


def build_report(
    *,
    states: list[str],
    index_close: pd.Series,
    unknown_state: str = "UNKNOWN",
    notes: list[str] | None = None,
) -> WalkForwardReport:
    summaries = state_summary(states)
    unknown_days = states.count(unknown_state)
    return WalkForwardReport(
        days=len(states),
        unknown_ratio=(unknown_days / len(states)) if states else 0.0,
        switch_count=switch_count(states),
        states=summaries,
        outcomes=forward_outcomes(
            states=states, index_close=index_close, unknown_state=unknown_state
        ),
        notes=notes or [],
    )


def render_markdown(report: WalkForwardReport, *, title: str, context: list[str]) -> str:
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
        "| 状态 | 天数 | 占比 | 平均持续 | 中位持续 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for state_row in report.states:
        average = "—" if state_row.average_duration is None else f"{state_row.average_duration:.1f}"
        med = "—" if state_row.median_duration is None else f"{state_row.median_duration:.1f}"
        lines.append(
            f"| {state_row.state} | {state_row.days} | {state_row.share:.1%} | {average} | {med} |"
        )

    lines += [
        "",
        "## 2. 状态之后的收益与回撤分布",
        "",
        "单位为百分比；样本为该状态出现的次数（不含观察期不足的样本）。",
        "",
        "| 状态 | 窗口 | 样本 | 收益均值 | 收益中位 | 收益 p10 | 收益 p90 | 回撤均值 | 最深回撤 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for outcome in report.outcomes:
        if outcome.sample_size == 0:
            lines.append(f"| {outcome.state} | {outcome.window}日 | 0 | — | — | — | — | — | — |")
            continue
        lines.append(
            f"| {outcome.state} | {outcome.window}日 | {outcome.sample_size} "
            f"| {outcome.return_mean:+.2%} | {outcome.return_median:+.2%} "
            f"| {outcome.return_p10:+.2%} | {outcome.return_p90:+.2%} "
            f"| {outcome.max_drawdown_mean:+.2%} | {outcome.max_drawdown_worst:+.2%} |"
        )

    if report.notes:
        lines += ["", "## 3. 说明与边界", ""]
        lines += [f"- {note}" for note in report.notes]
    lines += [
        "",
        "---",
        "",
        "本文只描述统计事实，不含任何“必涨”“胜率保证”之类的结论；",
        "阈值优化被明确排除在 V2 范围之外（见 `docs/WATCHBOARD.md` 与升级方案 §6.3）。",
        "",
    ]
    return "\n".join(lines)
