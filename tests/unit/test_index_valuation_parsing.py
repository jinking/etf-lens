"""指数估值适配器：解析与"逐指数有界重试"。

上游（乐咕）对中证500 / 中证1000 等指数会间歇性抛异常，实测同一个 symbol
有时成功有时失败。因此重试是**必需**行为，不是优化；而重试仍失败时必须
如实记 issue，不能返回空表冒充"该指数没有估值"。
"""

from datetime import date, datetime

import pandas as pd

from etf_engine.sources.akshare import index_valuation as module
from etf_engine.sources.akshare.index_valuation import (
    AkshareIndexValuationSource,
    parse_index_valuation_frame,
)

FETCHED_AT = datetime(2026, 9, 12, 10, 0)


def _frame(rows: int = 3) -> pd.DataFrame:
    dates = ["2026-01-30", "2026-02-27", "2026-03-31"]
    return pd.DataFrame(
        [
            {
                "日期": dates[index % len(dates)],
                "指数": 4000.0 + index,
                "等权静态市盈率": 30.0 + index,
                "静态市盈率": 20.0 + index,
                "静态市盈率中位数": 25.0 + index,
                "等权滚动市盈率": 28.0 + index,
                "滚动市盈率": 18.0 + index,
                "滚动市盈率中位数": 23.0 + index,
            }
            for index in range(rows)
        ]
    )


def test_parse_keeps_all_six_pe_variants():
    rows, issues = parse_index_valuation_frame(_frame(), index_id="000300", fetched_at=FETCHED_AT)

    assert issues == []
    assert len(rows) == 3
    assert float(rows[-1].pe_ttm) == 20.0
    assert float(rows[-1].pe_ttm_median) == 25.0
    assert float(rows[-1].pe_ttm_equal_weight) == 30.0
    assert rows[-1].trade_date == date(2026, 3, 31)
    assert rows[-1].metric_basis == "lg_index_pe_monthly"


def test_parse_skips_rows_without_pe_and_records_issue():
    frame = _frame()
    frame.loc[0, ["静态市盈率", "滚动市盈率"]] = None

    rows, issues = parse_index_valuation_frame(frame, index_id="000300", fetched_at=FETCHED_AT)

    assert len(rows) == 2
    assert any(issue.rule_name == "index_valuation_pe_missing" for issue in issues)


def test_uncovered_index_is_reported_not_substituted(monkeypatch):
    source = AkshareIndexValuationSource()
    rows, issues = source.fetch_index_valuations(["399006"])

    assert rows == []
    assert issues and issues[0].rule_name == "index_valuation_symbol_missing"
    assert "399006" in issues[0].details


def test_transient_upstream_failure_is_retried(monkeypatch):
    calls = {"count": 0}

    def _flaky(symbol: str):
        calls["count"] += 1
        if calls["count"] < 3:
            raise AttributeError("'NoneType' object has no attribute 'attrs'")
        return _frame()

    monkeypatch.setattr(module.ak, "stock_index_pe_lg", _flaky)
    source = AkshareIndexValuationSource()

    rows, issues = source.fetch_index_valuations(["000905"], sleep_seconds=0.0)

    assert calls["count"] == 3
    assert len(rows) == 3
    assert issues == []


def test_persistent_failure_is_recorded_with_attempt_count(monkeypatch):
    def _always_fail(symbol: str):
        raise AttributeError("'NoneType' object has no attribute 'attrs'")

    monkeypatch.setattr(module.ak, "stock_index_pe_lg", _always_fail)
    source = AkshareIndexValuationSource()

    rows, issues = source.fetch_index_valuations(["000905"], attempts=2, sleep_seconds=0.0)

    assert rows == []
    assert issues[0].rule_name == "index_valuation_fetch_failed"
    assert "重试 2 次仍失败" in issues[0].details
