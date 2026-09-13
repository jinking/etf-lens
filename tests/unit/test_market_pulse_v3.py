"""实验版 v3：只换输入尺度，阈值与状态机沿用 v2，且不落库。"""

from datetime import date, timedelta

import pytest

from etf_engine.domain.versions import PULSE_V3_EXPERIMENTAL_VERSION
from etf_engine.research.market_pulse import LayerResult, LayerState
from etf_engine.research.market_pulse_v3 import (
    VERSION,
    evaluate_liquidity_v3,
    evaluate_v3,
    evaluate_volume_v3,
)


def _series(values: list[float]) -> list[dict]:
    return [
        {"trade_date": date(2026, 1, 1) + timedelta(days=index), "value": value}
        for index, value in enumerate(values)
    ]


def test_version_is_registered_and_experimental():
    assert VERSION == PULSE_V3_EXPERIMENTAL_VERSION
    assert VERSION.startswith("pulse_v3")


def test_normalized_liquidity_needs_enough_history():
    result = evaluate_liquidity_v3(_series([0.02, 0.021]))

    assert result.state is LayerState.UNKNOWN
    assert "标准化两融序列不足" in result.note


def test_normalized_series_drives_the_state():
    # 前 240 天横盘、最后 6 天抬升 → 5 日变化为正
    values = [0.02] * 240 + [0.02, 0.021, 0.022, 0.023, 0.024, 0.025]

    result = evaluate_liquidity_v3(_series(values))

    assert result.metrics["margin_balance_ratio"] == 0.025
    assert result.metrics["margin_balance_5d_change_pct"] > 0


def test_missing_normalized_values_do_not_fall_back_to_absolute_levels():
    rows = _series([0.02] * 10)
    rows[-1]["value"] = None

    result = evaluate_liquidity_v3(rows)

    assert result.metrics["margin_balance_ratio"] == 0.02


def test_v3_combines_layers_without_persisting():
    margin = _series([0.02] * 250)
    turnover = _series([0.01] * 250)
    etf = LayerResult(LayerState.NEUTRAL, 0, "测试")

    result = evaluate_v3(margin_norm=margin, turnover_norm=turnover, etf_layer=etf)

    assert result.calculation_version == PULSE_V3_EXPERIMENTAL_VERSION
    assert result.known_layers == 3
    assert result.overall in {"偏多", "中性观望", "防守", "数据不足"}


def test_v3_volume_ratio_is_scale_invariant():
    """量比是比值：整体放大 10 倍不改变它（这正是标准化的意义所在）。"""
    base = _series([0.01] * 250)
    scaled = _series([0.1] * 250)

    assert evaluate_volume_v3(base).metrics["turnover_volume_ratio_5d"] == pytest.approx(
        evaluate_volume_v3(scaled).metrics["turnover_volume_ratio_5d"]
    )
