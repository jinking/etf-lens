"""`etf compare` 的行为基线。

Phase 1（Point-in-Time）会**故意**给输出加上 ``*_asof_date`` / ``*_staleness_days``，
届时这份契约要一起更新——更新本身就是"输出契约变了"的显式记录。
"""

import pytest

from etf_engine.services.research_service import ResearchService

#: Phase 0 冻结的 compare 输出契约（少一个字段、多一个字段都会失败）。
COMPARE_CONTRACT = [
    "security_id",
    "fund_name",
    "manager_name",
    "fund_type",
    "tracking_index_name",
    "close",
    "change_pct",
    "turnover_amount",
    "avg_turnover_amount_20d",
    "shares",
    "estimated_aum",
    "return_20d",
    "return_60d",
    "max_drawdown_60d",
    "share_change_20d",
    "share_change_pct_20d",
    "estimated_net_subscription_20d",
    "quote_asof_date",
]


def test_compare_output_contract_is_frozen(warehouse):
    rows = ResearchService().compare(["510300.SH", "159919.SZ"])

    assert len(rows) == 2
    assert list(rows[0]) == COMPARE_CONTRACT


def test_compare_values_match_the_seed(warehouse):
    rows = {
        row["security_id"]: row for row in ResearchService().compare(["510300.SH", "159919.SZ"])
    }
    first = rows["510300.SH"]

    # 收盘 = 100 + 24（第 25 个交易日）
    assert first["close"] == 124.0
    assert first["fund_name"] == "510300ETF"
    # master 的跟踪指数由 etf_index_map 的映射回填（基金披露口径）
    assert first["tracking_index_name"] == "沪深300指数"
    # 份额 1000 + 10×24 = 1240，净值 1.5 → 估算规模 1860
    assert first["shares"] == 1240.0
    assert first["estimated_aum"] == 1860.0
    # 20 日收益 = 124/104 - 1
    assert first["return_20d"] == pytest.approx(124 / 104 - 1)
    # 20 日均成交额 = mean(1_000_000 + 1000i, i=5..24)
    assert first["avg_turnover_amount_20d"] == pytest.approx(1_014_500)
    # 份额 20 日变化 = 200，估算申赎 = 20 × 10 × 1.5
    assert first["share_change_20d"] == 200.0
    assert first["estimated_net_subscription_20d"] == pytest.approx(300.0)
    assert first["quote_asof_date"].isoformat() == warehouse
    # 种子只有 25 个交易日：60 日窗口不足 → NULL（不用近似值凑）
    assert first["return_60d"] is None
    assert first["max_drawdown_60d"] is None


def test_compare_reports_the_same_seed_for_the_second_etf(warehouse):
    rows = {row["security_id"]: row for row in ResearchService().compare(["159919.SZ"])}
    second = rows["159919.SZ"]

    # 份额 2000 + 20×24 = 2480 → 规模 3720；20 日变化 400 → 申赎 600
    assert second["shares"] == 2480.0
    assert second["estimated_aum"] == 3720.0
    assert second["share_change_20d"] == 400.0
    assert second["estimated_net_subscription_20d"] == pytest.approx(600.0)


def test_compare_ignores_unknown_ids(warehouse):
    """非法代码被静默过滤（不报错、不编造行）。"""
    rows = ResearchService().compare(["510300.SH", "999999", "not-an-id"])

    assert [row["security_id"] for row in rows] == ["510300.SH"]
