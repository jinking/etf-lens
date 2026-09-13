"""walk-forward 统计：只描述事实，不做阈值寻优。"""

import pandas as pd
import pytest

from etf_engine.research.walk_forward import (
    build_report,
    forward_outcomes,
    render_markdown,
    state_durations,
    state_summary,
    switch_count,
)


def test_state_durations_counts_continuous_runs():
    states = ["A", "A", "B", "B", "B", "A"]

    assert state_durations(states) == {"A": [2, 1], "B": [3]}


def test_state_summary_reports_share_and_duration():
    states = ["A", "A", "B", "UNKNOWN"]

    summary = {item.state: item for item in state_summary(states)}

    assert summary["A"].days == 2
    assert summary["A"].share == pytest.approx(0.5)
    assert summary["A"].average_duration == pytest.approx(2.0)
    assert summary["UNKNOWN"].days == 1


def test_switch_count_counts_state_changes():
    assert switch_count(["A", "A", "B", "B", "A"]) == 2
    assert switch_count(["A", "A"]) == 0
    assert switch_count([]) == 0


def test_forward_outcomes_skip_unknown_and_incomplete_windows():
    states = ["STRONG", "UNKNOWN", "STRONG", "WEAK"]
    close = pd.Series([100.0, 101.0, 102.0, 103.0, 104.0, 105.0])

    outcomes = {
        (item.state, item.window): item
        for item in forward_outcomes(states=states, index_close=close)
    }

    strong_5d = outcomes[("STRONG", 5)]
    # 第 0 天 STRONG 有完整 5 日窗口；第 2 天 STRONG 窗口不足
    assert strong_5d.sample_size == 1
    assert strong_5d.return_mean == pytest.approx(105 / 100 - 1)
    assert outcomes[("UNKNOWN", 5)].sample_size == 0, "UNKNOWN 不计入后续收益"
    assert outcomes[("WEAK", 5)].sample_size == 0


def test_forward_outcomes_include_drawdown_distribution():
    # 8 个观测 → 5 日窗口在第 0/1/2 个位置都有完整观察期
    states = ["STRONG"] * 8
    close = pd.Series([100.0, 120.0, 90.0, 100.0, 110.0, 115.0, 112.0, 118.0])

    outcome = next(
        item
        for item in forward_outcomes(states=states, index_close=close)
        if item.window == 5 and item.sample_size
    )

    assert outcome.sample_size == 3
    # 最深的一次来自以 120 为起点的那笔（5 日内跌到 90）→ -25%
    assert outcome.max_drawdown_worst == pytest.approx(-0.25)
    assert outcome.max_drawdown_mean is not None


def test_report_renders_tables_and_the_no_optimization_note():
    states = ["STRONG", "STRONG", "WEAK"]
    close = pd.Series([100.0, 101.0, 102.0, 103.0])

    report = build_report(states=states, index_close=close, notes=["口径说明"])
    markdown = render_markdown(report, title="t", context=["ctx"])

    assert "| 状态 | 天数 | 占比 | 平均持续 | 中位持续 |" in markdown
    assert "覆盖交易日：**3**" in markdown
    assert "阈值优化被明确排除" in markdown
    assert "口径说明" in markdown


def test_empty_history_produces_zeroed_report():
    report = build_report(states=[], index_close=pd.Series(dtype="float64"))

    assert report.days == 0
    assert report.unknown_ratio == 0.0
    assert report.switch_count == 0
