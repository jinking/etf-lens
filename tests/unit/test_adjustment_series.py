"""复权序列：2:1 折算、分红、无事实不擅自复权、Point-in-Time 安全。"""

from datetime import date, datetime
from decimal import Decimal

import pytest

from etf_engine.domain.enums import CorporateActionType, QualityStatus
from etf_engine.domain.models import ETFCorporateAction, SourceMeta
from etf_engine.research.adjustment import (
    AdjustmentInputs,
    build_adjusted_series,
    share_factor_on,
)

FETCHED_AT = datetime(2026, 9, 12, 18, 0)
D1, D2, D3, D4 = (
    date(2026, 7, 1),
    date(2026, 7, 2),
    date(2026, 7, 3),
    date(2026, 7, 6),
)


def _meta() -> SourceMeta:
    return SourceMeta(source="test", fetched_at=FETCHED_AT, quality_status=QualityStatus.PASS)


def _split(action_date: date, factor: str) -> ETFCorporateAction:
    share = Decimal(factor)
    return ETFCorporateAction(
        security_id="515880.SH",
        action_date=action_date,
        action_type=CorporateActionType.SPLIT,
        split_ratio=f"1:{factor}",
        share_adjustment_factor=share,
        nav_adjustment_factor=Decimal(1) / share,
        source_meta=_meta(),
    )


def test_two_for_one_split_keeps_the_series_continuous():
    """515880 实测数据：净值折算日当日折半，价格次日才折半。

    原始序列：

    ```text
    净值  07-02 1.5774 → 07-03 0.7885（折算日当日生效）
    价格  07-03 1.579  → 07-06 0.757 （次一交易日生效）
    ```
    """
    d5 = date(2026, 7, 7)
    inputs = AdjustmentInputs(
        security_id="515880.SH",
        closes=[
            (D2, Decimal("1.576")),
            (D3, Decimal("1.579")),
            (D4, Decimal("0.757")),
            (d5, Decimal("0.761")),
        ],
        navs=[(D2, Decimal("1.5774")), (D3, Decimal("0.7885")), (D4, Decimal("0.7602"))],
        shares=[(D2, Decimal("100")), (D3, Decimal("200")), (D4, Decimal("200"))],
        actions=[_split(D3, "2.0000")],
    )

    points, issues = build_adjusted_series(inputs)

    assert issues == []
    by_date = {point.trade_date: point for point in points}
    # 基金层面：折算日当天生效
    assert by_date[D2].adjustment_factor == Decimal(1)
    assert by_date[D3].adjustment_factor == Decimal(2)
    assert by_date[D3].adjusted_nav == pytest.approx(Decimal("1.577"), abs=Decimal("0.001"))
    # 价格层面：折算日当天仍是折算前价格，因子从次一交易日开始
    assert by_date[D3].price_adjustment_factor == Decimal(1)
    assert by_date[D4].price_adjustment_factor == Decimal(2)
    assert by_date[D3].adjusted_close == Decimal("1.579")
    assert by_date[D4].adjusted_close == pytest.approx(Decimal("1.514"), abs=Decimal("0.001"))
    # 复权后价格连续（无假的 ±50% 跳变）；份额在复权口径下连续
    assert by_date[D4].adjusted_close / by_date[D3].adjusted_close == pytest.approx(
        Decimal("0.9588"), abs=Decimal("0.001")
    )
    assert by_date[D2].adjusted_shares == Decimal("100")
    assert by_date[D3].adjusted_shares == Decimal("100")


def test_dividend_adjustment_uses_the_previous_close_only():
    dividend = ETFCorporateAction(
        security_id="510300.SH",
        action_date=D3,
        action_type=CorporateActionType.DIVIDEND,
        cash_distribution=Decimal("0.1"),
        source_meta=_meta(),
    )
    inputs = AdjustmentInputs(
        security_id="510300.SH",
        closes=[
            (D1, Decimal("4.00")),
            (D2, Decimal("4.00")),
            (D3, Decimal("4.00")),
            (D4, Decimal("3.90")),
        ],
        navs=[],
        shares=[],
        actions=[dividend],
    )

    points, issues = build_adjusted_series(inputs)

    assert issues == []
    by_date = {point.trade_date: point for point in points}
    assert by_date[D2].adjustment_factor == Decimal(1)
    # 除息日 07-03：价格从次一交易日（07-06）起用因子 4.00 / (4.00 - 0.10)
    assert by_date[D3].price_adjustment_factor == Decimal(1)
    assert by_date[D4].price_adjustment_factor == pytest.approx(
        Decimal("1.025641"), abs=Decimal("1e-6")
    )
    assert by_date[D4].adjusted_close == pytest.approx(Decimal("4.00"), abs=Decimal("0.001"))


def test_dividend_without_previous_close_is_skipped_and_reported():
    dividend = ETFCorporateAction(
        security_id="510300.SH",
        action_date=D3,
        action_type=CorporateActionType.DIVIDEND,
        cash_distribution=Decimal("0.1"),
        source_meta=_meta(),
    )
    inputs = AdjustmentInputs(
        security_id="510300.SH",
        # 序列从除息日之后才开始：拿不到除息前收盘价
        closes=[(D4, Decimal("3.90"))],
        navs=[],
        shares=[],
        actions=[dividend],
    )

    points, issues = build_adjusted_series(inputs)

    assert points[0].adjustment_factor == Decimal(1)
    assert [issue.rule_name for issue in issues] == ["dividend_adjustment_skipped"]


def test_without_action_facts_nothing_is_adjusted():
    """没有公司行为事实时绝不擅自复权（跳变只能"发现异常"，不能"创建事实"）。"""
    inputs = AdjustmentInputs(
        security_id="999999.SH",
        closes=[(D1, Decimal("10")), (D2, Decimal("5"))],
        navs=[],
        shares=[],
        actions=[],
    )

    points, _ = build_adjusted_series(inputs)

    assert [point.adjustment_factor for point in points] == [Decimal(1), Decimal(1)]
    assert [point.adjusted_close for point in points] == [Decimal("10"), Decimal("5")]


def test_factor_at_a_past_date_never_uses_future_actions():
    """Point-in-Time：折算日之前的行因子必须是 1，不能被未来的折算改写。"""
    inputs = AdjustmentInputs(
        security_id="588200.SH",
        # 折算日 D3，价格从次一交易日 D4 起生效
        closes=[(D1, Decimal("3.0")), (D4, Decimal("1.0")), (date(2026, 7, 7), Decimal("1.05"))],
        navs=[],
        shares=[],
        actions=[_split(D3, "3.0000")],
    )

    points, _ = build_adjusted_series(inputs)
    by_date = {point.trade_date: point for point in points}

    assert by_date[D1].adjustment_factor == Decimal(1)
    assert by_date[D1].adjusted_close == Decimal("3.0"), "历史行不因未来折算而改变"
    assert by_date[D4].price_adjustment_factor == Decimal(3)
    assert by_date[D4].adjusted_close == Decimal("3.0")


def test_share_factor_on_returns_one_on_ordinary_days():
    assert share_factor_on([_split(D3, "2")], D1) == Decimal(1)
    assert share_factor_on([_split(D3, "2")], D3) == Decimal(2)


def test_reverse_split_factor_is_below_one():
    reverse = ETFCorporateAction(
        security_id="510300.SH",
        action_date=D3,
        action_type=CorporateActionType.REVERSE_SPLIT,
        split_ratio="1:0.3709",
        share_adjustment_factor=Decimal("0.3709"),
        nav_adjustment_factor=Decimal(1) / Decimal("0.3709"),
        source_meta=_meta(),
    )

    assert share_factor_on([reverse], D3) == Decimal("0.3709")
