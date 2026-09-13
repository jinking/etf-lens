"""同类分组与分位：优先级明确、样本不足不给分位、方向统一。"""

import pytest

from etf_engine.research.peer import (
    KIND_BENCHMARK_NAME,
    KIND_TAG,
    KIND_TRACKING_INDEX,
    MIN_PEER_COUNT,
    assign_peer_group,
    group_members,
    percentile,
)


def test_tracking_index_wins_over_name_and_tag():
    group = assign_peer_group(
        security_id="510300.SH",
        tracking_index_id="000300",
        tracking_index_name="沪深300指数",
        primary_tag="电力设备",
    )

    assert group.kind == KIND_TRACKING_INDEX
    assert group.peer_group_id == "index:000300"


def test_name_is_used_when_the_code_is_missing():
    group = assign_peer_group(
        security_id="588200.SH",
        tracking_index_id=None,
        tracking_index_name="上证科创板芯片指数",
    )

    assert group.kind == KIND_BENCHMARK_NAME
    assert group.peer_group_id == "benchmark:上证科创板芯片指数"


def test_tag_is_only_a_fallback():
    group = assign_peer_group(security_id="510300.SH", primary_tag="半导体")

    assert group.kind == KIND_TAG
    assert group.peer_group_id == "tag:半导体"


def test_without_any_basis_there_is_no_group():
    """没有跟踪指数也没有标签 → 不分组，绝不用名称模糊匹配凑一个同类。"""
    assert assign_peer_group(security_id="999999.SH") is None


def test_percentile_is_direction_aware():
    values = [1.0, 2.0, 3.0, 4.0]

    assert percentile(values, 4.0, higher_is_better=True) == pytest.approx(1.0)
    assert percentile(values, 1.0, higher_is_better=True) == pytest.approx(0.0)
    # 费用越低越好：数值最小的那个拿到最高分位（1.0 = 同类最优）
    assert percentile(values, 1.0, higher_is_better=False) == pytest.approx(1.0)
    assert percentile(values, 4.0, higher_is_better=False) == pytest.approx(0.0)
    # 两个方向都用同一把尺子：最好恒为 1、最差恒为 0
    # 中间值：比我差的有 2 个（1、2 或 3、4）→ 2/3
    assert percentile(values, 2.5, higher_is_better=True) == pytest.approx(2 / 3)
    assert percentile(values, 2.5, higher_is_better=False) == pytest.approx(2 / 3)


def test_percentile_needs_enough_peers():
    assert percentile([1.0, 2.0], 1.0, higher_is_better=True) is None
    assert MIN_PEER_COUNT == 3


def test_percentile_ignores_missing_values():
    values = [1.0, None, 3.0, None, 5.0]

    assert percentile(values, 3.0, higher_is_better=True) == pytest.approx(0.5)


def test_percentile_without_own_value_is_null():
    assert percentile([1.0, 2.0, 3.0], None, higher_is_better=True) is None


def test_group_members_are_deterministic():
    groups = [
        assign_peer_group(security_id="510310.SH", tracking_index_id="000300"),
        assign_peer_group(security_id="510300.SH", tracking_index_id="000300"),
        assign_peer_group(security_id="588200.SH", tracking_index_name="芯片指数"),
    ]

    members = group_members([group for group in groups if group])

    assert members["index:000300"] == ["510300.SH", "510310.SH"]
    assert members["benchmark:芯片指数"] == ["588200.SH"]
