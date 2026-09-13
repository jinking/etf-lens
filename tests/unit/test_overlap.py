"""持仓重合度：四种口径分开给，不合成分数。"""

import pytest

from etf_engine.research.overlap import (
    holding_overlap,
    industry_overlap,
    industry_weights,
)


def _holdings(*pairs: tuple[str, float]) -> list[dict]:
    return [
        {"stock_id": stock_id, "stock_name": stock_id, "weight_pct": weight}
        for stock_id, weight in pairs
    ]


def test_identical_portfolios_overlap_fully():
    a = _holdings(("600519.SH", 5.0), ("300750.SZ", 3.0))
    b = _holdings(("600519.SH", 5.0), ("300750.SZ", 3.0))

    result = holding_overlap(a, b)

    assert result.holding_overlap_ratio == 1.0
    assert result.weighted_overlap == pytest.approx(8.0)
    assert result.common_holdings == ["300750.SZ", "600519.SH"]


def test_disjoint_portfolios_have_no_overlap():
    a = _holdings(("600519.SH", 5.0))
    b = _holdings(("300750.SZ", 3.0))

    result = holding_overlap(a, b)

    assert result.holding_overlap_ratio == 0.0
    assert result.weighted_overlap == 0.0
    assert result.common_holdings == []


def test_partial_overlap_uses_the_smaller_side_as_denominator():
    """A 有 1 只、B 有 3 只，共同 1 只 → 以较少一方为分母，重合度 100%。"""
    a = _holdings(("600519.SH", 5.0))
    b = _holdings(("600519.SH", 4.0), ("300750.SZ", 3.0), ("000001.SZ", 1.0))

    result = holding_overlap(a, b)

    assert result.holding_overlap_ratio == 1.0
    assert result.weighted_overlap == pytest.approx(4.0), "按 min(权重) 口径"


def test_top10_overlap_counts_only_the_top_ten():
    a = _holdings(*[(f"{index:06d}.SZ", float(index)) for index in range(1, 13)])
    b = _holdings(*[(f"{index:06d}.SZ", float(index)) for index in range(6, 16)])

    result = holding_overlap(a, b)

    # A 的 top10 是权重 12..3（代码 12..3），B 的 top10 是 15..6
    # → 交集是代码 6..12，共 7 只
    assert result.top10_overlap == pytest.approx(0.7)


def test_empty_side_returns_nulls_not_zeros():
    result = holding_overlap([], _holdings(("600519.SH", 5.0)))

    assert result.holding_overlap_ratio is None
    assert result.weighted_overlap is None


def test_industry_overlap_uses_minimum_weights():
    a = {"半导体": 40.0, "医药生物": 10.0}
    b = {"半导体": 30.0, "电力设备": 20.0}

    assert industry_overlap(a, b) == pytest.approx(30.0)


def test_industry_weights_keep_unclassified_holdings():
    holdings = _holdings(("600519.SH", 5.0), ("999999.SZ", 2.0))

    weights = industry_weights(holdings, {"600519.SH": "食品饮料"})

    assert weights["食品饮料"] == pytest.approx(5.0)
    assert weights["__unclassified__"] == pytest.approx(2.0), "未分类的样本不丢"
