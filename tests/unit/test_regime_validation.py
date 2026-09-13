"""Historical Regime Validation：只描述事实，不做阈值寻优，样本口径必须分开。"""

from datetime import date

import pandas as pd
import pytest

from etf_engine.research.regime_validation import (
    SAMPLE_DAILY,
    SAMPLE_TRANSITION,
    build_regime_slices,
    build_report,
    forward_outcomes,
    render_markdown,
    state_durations,
    state_entries,
    state_summary,
    switch_count,
)


def test_state_durations_counts_continuous_runs():
    states = ["A", "A", "B", "B", "B", "A"]

    assert state_durations(states) == {"A": [2, 1], "B": [3]}


def test_state_entries_are_first_day_plus_every_switch():
    assert state_entries(["A", "A", "B", "B", "A", "C"]) == [0, 2, 4, 5]
    assert state_entries([]) == []
    assert state_entries(["A", "A", "A"]) == [0]


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


def test_daily_and_transition_samples_are_reported_separately():
    """连续 10 天同一状态：daily 记 10 条，transition 只记进入那 1 天。"""
    states = ["STRONG"] * 10 + ["WEAK"] * 10
    close = pd.Series([100.0 + index for index in range(20)])

    outcomes = {
        (item.state, item.window): item
        for item in forward_outcomes(states=states, index_close=close)
    }

    strong = outcomes[("STRONG", 5)]
    assert strong.daily.sample_count == 10
    assert strong.transition.sample_count == 1
    # 兼容旧字段名：sample_size 等价于 daily 样本数。
    assert strong.sample_size == strong.daily.sample_count

    weak = outcomes[("WEAK", 5)]
    # 窗口 5 日：末 5 天没有完整观察期，因此 daily 记 5 条而不是 10 条。
    assert weak.daily.sample_count == 5
    assert weak.transition.sample_count == 1


def test_forward_outcomes_skip_unknown_and_incomplete_windows():
    states = ["STRONG", "UNKNOWN", "STRONG", "WEAK"]
    close = pd.Series([100.0, 101.0, 102.0, 103.0, 104.0, 105.0])

    outcomes = {
        (item.state, item.window): item
        for item in forward_outcomes(states=states, index_close=close)
    }

    strong_5d = outcomes[("STRONG", 5)]
    # 第 0 天 STRONG 有完整 5 日窗口；第 2 天 STRONG 窗口不足
    assert strong_5d.daily.sample_count == 1
    assert strong_5d.daily.return_mean == pytest.approx(105 / 100 - 1)
    assert outcomes[("UNKNOWN", 5)].daily.sample_count == 0, "UNKNOWN 不计入后续收益"
    assert outcomes[("WEAK", 5)].daily.sample_count == 0
    # transition 起点集合同样跳过 UNKNOWN（第 1 天是 UNKNOWN 的进入日）
    assert outcomes[("UNKNOWN", 5)].transition.sample_count == 0


def test_forward_outcomes_include_drawdown_distribution():
    # 8 个观测 → 5 日窗口在第 0/1/2 个位置都有完整观察期
    states = ["STRONG"] * 8
    close = pd.Series([100.0, 120.0, 90.0, 100.0, 110.0, 115.0, 112.0, 118.0])

    outcome = next(
        item
        for item in forward_outcomes(states=states, index_close=close)
        if item.window == 5 and item.daily.sample_count
    )

    assert outcome.daily.sample_count == 3
    # 最深的一次来自以 120 为起点的那笔（5 日内跌到 90）→ -25%
    assert outcome.daily.max_drawdown_worst == pytest.approx(-0.25)
    assert outcome.daily.max_drawdown_mean is not None
    assert outcome.transition.sample_count == 1, "整段 STRONG 只算进入一次"


def test_build_regime_slices_splits_by_calendar_year_and_keeps_cross_year_windows():
    dates = [date(2024, 12, 30), date(2024, 12, 31), date(2024, 12, 31)] + [
        date(2025, 1, 2),
        date(2025, 1, 3),
        date(2025, 1, 6),
    ]
    states = ["A", "A", "B", "A", "A", "B"]
    close = pd.Series([100.0, 101.0, 102.0, 103.0, 104.0, 110.0])

    regimes = build_regime_slices(
        states=states, index_close=close, dates=dates, unknown_state="UNKNOWN"
    )

    assert [item.label for item in regimes] == ["2024", "2025"]
    assert regimes[0].days == 3
    assert regimes[1].days == 3
    # 2024-12-30 的 5 日窗口落在 2025 年，跨年不被截断
    a_2024 = next(item for item in regimes[0].outcomes if item.state == "A" and item.window == 5)
    assert a_2024.daily.sample_count == 1
    # 起点 2024-12-30、终点 2025-01-06：收益按跨年窗口算出来，不是 NULL
    assert a_2024.daily.return_mean == pytest.approx(110.0 / 100.0 - 1)


def test_report_renders_year_tables_and_the_no_optimization_note():
    dates = [date(2024, 1, 2)] * 3 + [date(2025, 1, 2)] * 3
    states = ["STRONG", "STRONG", "WEAK", "WEAK", "WEAK", "STRONG"]
    close = pd.Series([100.0, 101.0, 102.0, 103.0, 104.0, 105.0])

    report = build_report(states=states, index_close=close, dates=dates, notes=["口径说明"])
    markdown = render_markdown(report, title="t", context=["ctx"])

    assert report.days == 6
    assert [item.label for item in report.regimes] == ["2024", "2025"]
    assert "| 状态 | 天数 | 占比 | 平均持续 | 中位持续 |" in markdown
    assert "覆盖交易日：**6**" in markdown
    assert "daily 样本" in markdown
    assert "transition 样本" in markdown
    assert "## 4. 分 regime 视图" in markdown
    assert "阈值优化被明确排除" in markdown
    assert "口径说明" in markdown
    assert SAMPLE_DAILY and SAMPLE_TRANSITION  # 常量可被外部引用


def test_empty_history_produces_zeroed_report():
    report = build_report(states=[], index_close=pd.Series(dtype="float64"))

    assert report.days == 0
    assert report.unknown_ratio == 0.0
    assert report.switch_count == 0
    assert report.outcomes == []
    assert report.regimes == []


def test_every_markdown_table_is_rectangular():
    """空样本行（全是 —）最容易把列数写错，写错 Markdown 会整表错位。"""
    dates = [date(2024, 1, 2)] * 4 + [date(2025, 1, 2)] * 4
    states = ["UNKNOWN", "UNKNOWN", "STRONG", "WEAK", "WEAK", "WEAK", "STRONG", "STRONG"]
    close = pd.Series([100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 106.0, 107.0])
    report = build_report(states=states, index_close=close, dates=dates)

    markdown = render_markdown(report, title="t", context=[])

    block: list[int] = []
    for line in [*markdown.splitlines(), ""]:
        if line.startswith("|"):
            block.append(len([cell for cell in line.split("|")[1:-1]]))
            continue
        if block:
            assert len(set(block)) == 1, f"表内列数不一致：{block}"
            block = []


def test_walk_forward_module_stays_a_compatibility_wrapper():
    from etf_engine.research import walk_forward

    assert walk_forward.WalkForwardReport is walk_forward.RegimeValidationReport
    assert walk_forward.state_entries(["A", "B"]) == [0, 1]
