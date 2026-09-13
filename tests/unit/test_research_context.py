"""as-of 策略的边界：未来数据、过期数据、口径版本、同交易日要求。"""

from datetime import date

import pytest

from etf_engine.domain.research_context import (
    REASON_FUTURE,
    REASON_MISSING,
    REASON_NOT_SAME_DAY,
    REASON_STALE,
    REASON_VERSION_MISMATCH,
    ResearchContext,
    apply_context,
    evaluate_block,
)

ASOF = date(2026, 9, 11)


def test_latest_mode_does_not_judge_staleness():
    context = ResearchContext()
    status = evaluate_block(context, date(2026, 9, 10))

    assert status.dropped is False
    assert status.staleness_days is None, "没有 as-of 就算不出新鲜度，不能瞎编"


def test_future_block_is_rejected():
    context = ResearchContext(asof_date=ASOF)
    status = evaluate_block(context, date(2026, 9, 12))

    assert status.dropped is True
    assert status.reason == REASON_FUTURE


def test_missing_block_is_rejected_not_filled():
    status = evaluate_block(ResearchContext(asof_date=ASOF), None)

    assert status.dropped is True
    assert status.reason == REASON_MISSING
    assert status.staleness_days is None


def test_staleness_days_counts_calendar_days():
    context = ResearchContext(asof_date=ASOF, max_staleness_days=3)

    assert evaluate_block(context, date(2026, 9, 9)).staleness_days == 2
    assert evaluate_block(context, date(2026, 9, 9)).dropped is False
    assert evaluate_block(context, date(2026, 9, 8)).reason is None
    assert evaluate_block(context, date(2026, 9, 7)).reason == REASON_STALE


def test_require_same_trade_date_rejects_any_lag():
    context = ResearchContext(asof_date=ASOF, require_same_trade_date=True)

    assert evaluate_block(context, ASOF).dropped is False
    older = evaluate_block(context, date(2026, 9, 10))
    assert older.dropped is True
    assert older.reason == REASON_NOT_SAME_DAY


def test_require_same_trade_date_needs_an_asof():
    with pytest.raises(ValueError):
        ResearchContext(require_same_trade_date=True)


def test_negative_staleness_is_rejected():
    with pytest.raises(ValueError):
        ResearchContext(asof_date=ASOF, max_staleness_days=-1)


def test_apply_context_nulls_rejected_blocks_and_reports_reasons():
    context = ResearchContext(asof_date=ASOF, max_staleness_days=0)
    row = {
        "security_id": "510300.SH",
        "quote_asof_date": ASOF,
        "close": 1.23,
        "share_asof_date": date(2026, 9, 10),
        "shares": 100.0,
        "metric_asof_date": ASOF,
        "return_20d": 0.05,
        "flow_asof_date": None,
        "share_change_20d": 10.0,
    }

    result = apply_context(row, context)

    # quote / metric 同一天 → 保留
    assert result["close"] == 1.23
    assert result["return_20d"] == 0.05
    assert result["quote_staleness_days"] == 0
    # share 落后一天 → 置空
    assert result["shares"] is None
    assert result["share_staleness_days"] == 1
    # flow 完全缺失 → 置空
    assert result["share_change_20d"] is None
    assert result["flow_asof_date"] is None
    assert result["stale_blocks"] == ["share:stale", "flow:missing"]
    assert result["data_quality"] == "PARTIAL"
    assert result["research_asof_date"] == ASOF.isoformat()


def test_apply_context_rejects_mismatched_calculation_version():
    context = ResearchContext(
        asof_date=ASOF,
        calculation_versions={"metric": "metric_v2", "flow": "flow_v1"},
    )
    row = {
        "metric_asof_date": ASOF,
        "metric_calculation_version": "metric_v1",
        "return_20d": 0.05,
        "flow_asof_date": ASOF,
        "flow_calculation_version": "flow_v1",
        "share_change_20d": 10.0,
    }

    result = apply_context(row, context)

    assert result["return_20d"] is None
    assert f"metric:{REASON_VERSION_MISMATCH}" in result["stale_blocks"]
    assert result["share_change_20d"] == 10.0, "版本匹配的块不受影响"


def test_apply_context_keeps_everything_in_latest_mode():
    context = ResearchContext()
    row = {
        "quote_asof_date": date(2026, 9, 11),
        "close": 1.0,
        "share_asof_date": date(2026, 6, 1),
        "shares": 5.0,
        "metric_asof_date": date(2026, 9, 11),
        "return_20d": 0.01,
        "flow_asof_date": date(2026, 9, 11),
        "share_change_20d": 3.0,
    }

    result = apply_context(row, context)

    assert result["close"] == 1.0
    assert result["shares"] == 5.0
    assert result["stale_blocks"] == []
    assert result["research_asof_date"] is None
