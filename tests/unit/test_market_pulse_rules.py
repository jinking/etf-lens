"""三层看盘规则（pulse_v2）的边界测试。

规则是确定性代码，因此每个阈值两侧都要有用例；数据不足必须输出 UNKNOWN，
不允许用 0 或默认值凑出结论。
"""

from datetime import date, timedelta

import pytest

from etf_engine.research.market_pulse import (
    CONFIRM_DAYS,
    LayerState,
    OverallState,
    change_pct,
    confirm_states,
    detect_transitions,
    evaluate_etf_basket,
    evaluate_liquidity,
    evaluate_volume,
    overall_state,
    percentile_rank,
    quadrant_label,
    rolling_mean,
    step_confirmed,
)


def _series(values, key="margin_balance_total", start=date(2026, 1, 1)):
    return [
        {"trade_date": start + timedelta(days=index), key: value}
        for index, value in enumerate(values)
    ]


def test_change_pct_uses_observed_trading_days_only():
    values = [100.0, None, 110.0, 120.0]
    # 3 个有观测值，取最近 2 个区间的变化率
    assert change_pct(values, 2) == pytest.approx(20.0)
    assert change_pct([100.0, None], 5) is None
    assert change_pct([0.0, 1.0, 2.0], 2) is None


def test_percentile_rank_needs_min_samples_and_handles_ties():
    assert percentile_rank([1, 2, 3]) is None
    values = list(range(100))
    assert percentile_rank(values) == pytest.approx(0.995)
    # 全相等时取中点，不会被算成 0 或 1
    assert percentile_rank([5.0] * 100) == pytest.approx(0.5)


def test_rolling_mean_leaves_short_window_null():
    result = rolling_mean([1, 2, 3, 4], window=3)
    assert result[0] is None and result[1] is None
    assert result[2] == pytest.approx(2.0)


def test_liquidity_unknown_when_history_is_short():
    result = evaluate_liquidity(_series([1e12] * 3))
    assert result.state == LayerState.UNKNOWN
    assert "不足" in result.note


def test_liquidity_strong_when_margin_rises_above_threshold():
    balances = [1e12] * 60 + [1e12 * 1.01]
    result = evaluate_liquidity(_series(balances))
    assert result.state == LayerState.STRONG
    assert result.metrics["margin_balance_5d_change_pct"] > 0.5


def test_liquidity_weak_when_margin_falls():
    balances = [1e12] * 60 + [1e12 * 0.9]
    result = evaluate_liquidity(_series(balances))
    assert result.state == LayerState.WEAK
    assert result.score <= -1


def test_volume_unknown_without_enough_days():
    result = evaluate_volume(_series([1e11] * 4, key="turnover_amount_total"))
    assert result.state == LayerState.UNKNOWN


def test_volume_strong_when_turnover_expands():
    amounts = [1e11] * 60 + [2e11]
    result = evaluate_volume(_series(amounts, key="turnover_amount_total"))
    assert result.state == LayerState.STRONG
    assert result.metrics["turnover_volume_ratio_5d"] > 1.1


def test_volume_missing_series_is_null_not_zero():
    amounts = [1e11] * 60 + [None]
    result = evaluate_volume(_series(amounts, key="turnover_amount_total"))
    # 当日成交额为 NULL 时状态不可判定，且 NULL 绝不能被当成 0
    assert result.state == LayerState.UNKNOWN
    assert result.metrics["turnover_amount_total"] is None


def test_etf_basket_empty_is_unknown():
    result = evaluate_etf_basket({"basket_size": 0})
    assert result.state == LayerState.UNKNOWN
    assert "sync-index-map" in result.note


def test_etf_basket_inflow_is_strong():
    result = evaluate_etf_basket(
        {"basket_size": 3, "net_subscription_5d": 5e8, "net_subscription_20d": -1e8}
    )
    assert result.state == LayerState.NEUTRAL  # 一正一负 → 0 分
    result = evaluate_etf_basket(
        {"basket_size": 3, "net_subscription_5d": 5e8, "net_subscription_20d": 1e8}
    )
    assert result.state == LayerState.STRONG
    assert result.score == 2


def test_etf_basket_outflow_is_weak():
    result = evaluate_etf_basket(
        {"basket_size": 3, "net_subscription_5d": -5e8, "net_subscription_20d": -1e8}
    )
    assert result.state == LayerState.WEAK


def test_etf_basket_premium_is_displayed_but_not_scored():
    plain = evaluate_etf_basket(
        {"basket_size": 3, "net_subscription_5d": 1e8, "net_subscription_20d": 1e8}
    )
    with_premium = evaluate_etf_basket(
        {
            "basket_size": 3,
            "net_subscription_5d": 1e8,
            "net_subscription_20d": 1e8,
            # 明显溢价：文档说"持续大幅溢价 = 过热（警惕）"，方向不稳定，
            # 因此只出现在 note 里，不能改变分数
            "premium_median_pct": 0.012,
        }
    )
    assert with_premium.state == plain.state
    assert with_premium.score == plain.score
    assert "+1.20%" in with_premium.note


def test_overall_state_follows_the_documented_rule():
    states = {
        "liquidity": LayerState.STRONG,
        "volume": LayerState.STRONG,
        "etf": LayerState.WEAK,
    }
    assert overall_state(states) == (OverallState.BULLISH, 2, 3)

    states["volume"] = LayerState.NEUTRAL
    assert overall_state(states) == (OverallState.NEUTRAL, 1, 3)

    states["liquidity"] = LayerState.NEUTRAL
    assert overall_state(states) == (OverallState.DEFENSIVE, 0, 3)


def test_overall_state_refuses_to_conclude_with_one_layer():
    states = {
        "liquidity": LayerState.STRONG,
        "volume": LayerState.UNKNOWN,
        "etf": LayerState.UNKNOWN,
    }
    assert overall_state(states) == (OverallState.UNKNOWN, 1, 1)


def test_quadrant_label_matches_the_documented_cells():
    assert "低位放量" in quadrant_label(0.1, 1.5)
    assert "低位缩量" in quadrant_label(0.1, 0.5)
    assert "高位放量" in quadrant_label(0.9, 1.5)
    assert "高位缩量" in quadrant_label(0.9, 0.5)
    assert quadrant_label(0.5, 1.0) == "中位平量：信号不明确"
    assert quadrant_label(None, 1.5) is None


# ------------------------------------------------------------------ pulse_v2


def test_confirm_states_requires_two_consecutive_days():
    raw = ["NEUTRAL", "STRONG", "NEUTRAL", "STRONG", "STRONG", "WEAK"]
    # 第一天直接采用；STRONG 反复出现但不连续 → 不确认；
    # 连续两天 STRONG 才切换；随后单日 WEAK 不切换
    assert confirm_states(raw) == [
        "NEUTRAL",
        "NEUTRAL",
        "NEUTRAL",
        "NEUTRAL",
        "STRONG",
        "STRONG",
    ]


def test_confirm_states_ignores_alternating_noise():
    raw = ["STRONG", "WEAK", "STRONG", "WEAK", "STRONG", "WEAK", "STRONG"]
    assert set(confirm_states(raw)) == {"STRONG"}


def test_confirm_states_applies_unknown_immediately():
    raw = ["UNKNOWN", "UNKNOWN", "WEAK", "NEUTRAL", "NEUTRAL"]
    # 数据开始覆盖/中断是口径事件，不参与确认，立即生效
    assert confirm_states(raw) == ["UNKNOWN", "UNKNOWN", "WEAK", "WEAK", "NEUTRAL"]


def test_step_confirmed_matches_full_replay():
    """日更的单步确认必须与整段重放结果一致（否则日更与回放会分叉）。"""
    raw = ["NEUTRAL", "STRONG", "NEUTRAL", "STRONG", "STRONG", "WEAK", "WEAK"]
    full = confirm_states(raw)
    stepwise = []
    confirmed = None
    previous_raw = None
    for value in raw:
        confirmed = step_confirmed(confirmed_prev=confirmed, raw_prev=previous_raw, raw_today=value)
        stepwise.append(confirmed)
        previous_raw = value
    assert stepwise == full


def test_step_confirmed_defaults_to_two_day_window():
    assert CONFIRM_DAYS == 2
    with pytest.raises(ValueError):
        step_confirmed(confirmed_prev="WEAK", raw_prev="WEAK", raw_today="STRONG", confirm_days=3)


def _history_row(day, liquidity, volume, etf, overall, note="理由"):
    return {
        "trade_date": day,
        "liquidity_state": liquidity,
        "volume_state": volume,
        "etf_state": etf,
        "overall_state": overall,
        "liquidity_note": note,
        "volume_note": note,
        "etf_note": note,
    }


def test_detect_transitions_flags_leading_layer_and_significance():
    rows = [
        _history_row("2026-09-09", "NEUTRAL", "WEAK", "WEAK", "防守"),
        _history_row("2026-09-10", "STRONG", "WEAK", "WEAK", "防守"),
    ]
    events = detect_transitions(rows)

    assert len(events) == 1
    event = events[0]
    assert event["overall_changed"] is False
    assert event["leading_layer"] == "liquidity"
    assert event["kind"] == "market"
    # 只有流动性单层变化 → 文档里的"资金先行信号"
    assert event["significance"] == "资金先行信号"
    assert [layer["key"] for layer in event["changed_layers"]] == ["liquidity"]


def test_detect_transitions_marks_multi_layer_as_resonance():
    rows = [
        _history_row("2026-09-09", "NEUTRAL", "NEUTRAL", "WEAK", "中性观望"),
        _history_row("2026-09-10", "WEAK", "WEAK", "WEAK", "防守"),
    ]
    event = detect_transitions(rows)[0]

    assert event["leading_layer"] is None
    assert event["significance"] == "多层共振转向"
    assert event["overall_changed"] is True
    assert (event["from_state"], event["to_state"]) == ("中性观望", "防守")


def test_detect_transitions_separates_data_coverage_from_market_events():
    rows = [
        _history_row("2026-07-17", "NEUTRAL", "WEAK", "UNKNOWN", "中性观望"),
        _history_row("2026-07-20", "NEUTRAL", "WEAK", "WEAK", "防守"),
    ]
    event = detect_transitions(rows)[0]

    # 宽基 ETF 层从"数据不足"变成"有数据"是口径事件，不是市场事件
    assert event["kind"] == "coverage"
    assert event["significance"] == "数据开始覆盖/中断"


def test_detect_transitions_ignores_unchanged_days():
    rows = [
        _history_row("2026-09-09", "NEUTRAL", "WEAK", "WEAK", "防守"),
        _history_row("2026-09-10", "NEUTRAL", "WEAK", "WEAK", "防守"),
    ]
    assert detect_transitions(rows) == []
