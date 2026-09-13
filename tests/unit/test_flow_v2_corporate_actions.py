"""flow_v2：折算造成的机械份额变化不得被当成申赎。"""

from datetime import date, datetime
from decimal import Decimal

import pandas as pd

from etf_engine.domain.enums import CorporateActionType, QualityStatus
from etf_engine.domain.models import ETFCorporateAction, SourceMeta
from etf_engine.research.flow_v2 import (
    FLOW_QUALITY_ADJUSTED,
    FLOW_QUALITY_CLEAN,
    adjusted_share_change,
    estimated_subscription_v2,
    flow_v2_windows,
)

D1, D2, D3 = date(2026, 7, 1), date(2026, 7, 2), date(2026, 7, 3)
FETCHED_AT = datetime(2026, 9, 12, 18, 0)


def _meta() -> SourceMeta:
    """本文件自用的来源元数据：测试之间不互相 import，避免依赖包结构。"""
    return SourceMeta(source="test", fetched_at=FETCHED_AT, quality_status=QualityStatus.PASS)


def _split(action_date: date) -> ETFCorporateAction:
    return ETFCorporateAction(
        security_id="515880.SH",
        action_date=action_date,
        action_type=CorporateActionType.SPLIT,
        split_ratio="1:2.0000",
        share_adjustment_factor=Decimal(2),
        nav_adjustment_factor=Decimal("0.5"),
        source_meta=_meta(),
    )


def test_split_day_share_change_is_fully_mechanical():
    """份额翻倍但没有真实申赎：经济变化应为 0。"""
    change = adjusted_share_change(
        shares_prev=Decimal("1000000"),
        shares_now=Decimal("2000000"),
        trade_date=D3,
        actions=[_split(D3)],
    )

    assert change.mechanical_change == Decimal("1000000")
    assert change.economic_change == Decimal("0")
    assert change.quality_status == FLOW_QUALITY_ADJUSTED


def test_split_day_no_longer_creates_a_fake_subscription():
    """v1 会把折算算成 100 万份申购；v2 必须得到 0。"""
    shares_prev, shares_now = Decimal("1000000"), Decimal("2000000")
    nav = Decimal("0.7885")

    v1_value = (shares_now - shares_prev) * nav  # v1 的口径
    v2_value, status = estimated_subscription_v2(
        shares_prev=shares_prev,
        shares_now=shares_now,
        nav_now=nav,
        trade_date=D3,
        actions=[_split(D3)],
    )

    assert v1_value == Decimal("788500.0")
    assert v2_value == Decimal(0)
    assert status == FLOW_QUALITY_ADJUSTED


def test_real_subscription_on_a_split_day_is_kept():
    """折算当天真实申购 5 万份：v2 只保留经济部分。"""
    value, status = estimated_subscription_v2(
        shares_prev=Decimal("1000000"),
        shares_now=Decimal("2050000"),
        nav_now=Decimal("1.0"),
        trade_date=D3,
        actions=[_split(D3)],
    )

    assert value == Decimal("50000")
    assert status == FLOW_QUALITY_ADJUSTED


def test_ordinary_day_matches_v1_semantics():
    change = adjusted_share_change(
        shares_prev=Decimal("1000"),
        shares_now=Decimal("1100"),
        trade_date=D2,
        actions=[_split(D3)],
    )

    assert change.economic_change == Decimal("100")
    assert change.quality_status == FLOW_QUALITY_CLEAN


def test_missing_shares_yield_null_not_zero():
    value, _ = estimated_subscription_v2(
        shares_prev=None,
        shares_now=Decimal("100"),
        nav_now=Decimal("1"),
        trade_date=D2,
        actions=[],
    )

    assert value is None


def test_flow_v2_windows_ignore_the_mechanical_jump():
    """复权后的份额序列在折算日连续 → 窗口变化只反映真实申赎。"""
    frame = pd.DataFrame(
        {
            "adjusted_shares": [1000.0, 1010.0, 1010.0],
            "adjusted_nav": [1.0, 1.0, 1.0],
            "adjustment_factor": [1.0, 1.0, 2.0],
        },
        index=pd.to_datetime([D1, D2, D3]),
    )

    metrics, quality = flow_v2_windows(frame)

    assert quality == FLOW_QUALITY_ADJUSTED
    # 折算当天：份额从 1010 变 1010（复权口径），1 日变化为 0，估算申购为 0
    assert metrics["share_change_1d"] == 0.0
    assert metrics["estimated_1d"] == 0.0


def test_flow_v2_windows_express_changes_in_current_units():
    """份额变化按最新时点单位表达，金额与单位基准无关。

    ``adjusted_shares`` 是基础单位（折算前口径），``adjusted_nav`` 是同一基准的
    净值（＝原始净值 × U）。因此：

    ```text
    份额变化（最新单位）= Δ基础单位 × U = 10 × 2 = 20 份
    估算净申购（元）    = Δ基础单位 × adjusted_nav = 10 × 1.0 = 10 元
                        ＝ Δ最新单位 × 原始净值 = 20 × 0.5 = 10 元   （一致）
    ```
    """
    frame = pd.DataFrame(
        {
            "adjusted_shares": [1000.0, 1010.0, 1010.0, 1020.0],
            "adjusted_nav": [1.0, 1.0, 1.0, 1.0],
            "adjustment_factor": [1.0, 1.0, 2.0, 2.0],
        },
        index=pd.to_datetime([D1, D2, D3, date(2026, 7, 6)]),
    )

    metrics, _ = flow_v2_windows(frame)

    assert metrics["share_change_1d"] == 20.0
    assert metrics["estimated_1d"] == 10.0


def test_flow_v2_windows_are_null_when_nav_is_missing():
    frame = pd.DataFrame(
        {
            "adjusted_shares": [1000.0, 1010.0],
            "adjusted_nav": [None, None],
            "adjustment_factor": [1.0, 1.0],
        },
        index=pd.to_datetime([D1, D2]),
    )

    metrics, quality = flow_v2_windows(frame)

    assert metrics["estimated_1d"] is None
    assert metrics["share_change_1d"] == 10.0, "份额变化本身是可得事实"
    assert quality == FLOW_QUALITY_CLEAN
