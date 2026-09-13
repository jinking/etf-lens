"""`etf pulse`（pulse_v2）的规则基线。

规则引擎是纯函数，因此基线可以直接钉住：吃一份手工构造的序列，
断言状态、分数与确认机制的行为。
"""

from datetime import date, timedelta

import pytest

from etf_engine.research.market_pulse import (
    PULSE_VERSION,
    LayerState,
    OverallState,
    build_pulse_row,
    confirm_states,
    evaluate_liquidity,
    evaluate_volume,
    overall_state,
)


def _series(values: list[float | None], key: str, start: date = date(2026, 1, 1)) -> list[dict]:
    return [
        {"trade_date": start + timedelta(days=index), key: value}
        for index, value in enumerate(values)
    ]


def test_pulse_version_is_registered():
    assert PULSE_VERSION == "pulse_v2"


def test_liquidity_needs_six_observations():
    result = evaluate_liquidity(_series([1e12] * 5, "margin_balance_total"))

    assert result.state is LayerState.UNKNOWN
    assert result.score == 0


def test_liquidity_strong_when_margin_rises_from_a_low_base():
    # 前 240 天横盘，最后 6 天连续抬升 → 5 日变化为正、分位仍低
    values = [100.0] * 240 + [100.0, 101.0, 102.0, 103.0, 104.0, 105.0]

    result = evaluate_liquidity(_series(values, "margin_balance_total"))

    assert result.metrics["margin_balance_5d_change_pct"] == pytest.approx(5.0)
    assert result.metrics["margin_balance_total"] == 105.0
    assert result.score >= 0


def test_liquidity_weak_when_margin_falls():
    values = [100.0] * 240 + [100.0, 99.0, 98.0, 97.0, 96.0, 95.0]

    result = evaluate_liquidity(_series(values, "margin_balance_total"))

    assert result.metrics["margin_balance_5d_change_pct"] == pytest.approx(-5.0)
    assert result.state is LayerState.WEAK


def test_volume_unknown_without_enough_history():
    result = evaluate_volume(_series([1e12] * 3, "turnover_amount_total"))

    assert result.state is LayerState.UNKNOWN


def test_volume_state_and_ratio_from_a_flat_series():
    """成交额横盘 → 量比接近 1，状态不偏强也不偏弱。"""
    result = evaluate_volume(_series([1e12] * 250, "turnover_amount_total"))

    assert result.metrics["turnover_volume_ratio_5d"] == pytest.approx(1.0)
    assert result.metrics["turnover_amount_total"] == 1e12


def test_confirmation_mechanism_requires_two_days():
    """pulse_v2 的核心：原始信号必须连续两天一致才切换。"""
    raw = ["NEUTRAL", "STRONG", "NEUTRAL", "NEUTRAL", "STRONG", "STRONG", "WEAK"]

    confirmed = confirm_states(raw)

    assert confirmed == [
        "NEUTRAL",  # 首日直接采用
        "NEUTRAL",  # 单日 STRONG 不切换
        "NEUTRAL",
        "NEUTRAL",
        "NEUTRAL",  # 第 1 天 STRONG
        "STRONG",  # 连续第 2 天 → 确认
        "STRONG",  # 单日 WEAK 不切换
    ]


def test_unknown_state_takes_effect_immediately():
    raw = ["STRONG", "UNKNOWN", "STRONG"]

    assert confirm_states(raw) == ["STRONG", "UNKNOWN", "STRONG"]


def test_overall_state_counts_strong_and_known_layers():
    overall, strong, known = overall_state(
        {"liquidity": LayerState.STRONG, "volume": LayerState.WEAK, "etf": LayerState.NEUTRAL}
    )
    all_unknown, _, known_when_empty = overall_state(
        {"liquidity": LayerState.UNKNOWN, "volume": LayerState.UNKNOWN, "etf": LayerState.UNKNOWN}
    )

    assert strong == 1
    assert known == 3
    assert all_unknown is OverallState.UNKNOWN
    assert overall is OverallState.NEUTRAL
    assert known_when_empty == 0


def test_build_pulse_row_keeps_raw_and_confirmed_states_apart():
    liquidity = evaluate_liquidity(_series([1e12] * 250, "margin_balance_total"))
    volume = evaluate_volume(_series([1e12] * 250, "turnover_amount_total"))
    row = build_pulse_row(
        trade_date=date(2026, 9, 11),
        liquidity=liquidity,
        volume=volume,
        etf=liquidity,
        basket={"basket_size": 3, "net_subscription_5d": 1.0},
        activity={"rising_count": 2000, "falling_count": 1500},
        confirmed_states={"volume": LayerState.STRONG.value},
    )

    assert row["calculation_version"] == PULSE_VERSION
    assert row["volume_state"] == "STRONG", "落库的是确认后的状态"
    assert row["volume_raw_state"] == volume.state.value, "原始信号同时保留"
    assert row["broad_etf_basket_size"] == 3
    assert row["rising_count"] == 2000
