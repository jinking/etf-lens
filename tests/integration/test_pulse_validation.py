"""pulse_v2 验证与市场层标准化指标的端到端。"""

from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from etf_engine.config.settings import settings
from etf_engine.db.connection import connect
from etf_engine.db.migrate import run_migrations
from etf_engine.domain.enums import QualityStatus
from etf_engine.domain.models import IndexQuote, SourceMeta
from etf_engine.jobs.compute_market_norm import compute_market_norm
from etf_engine.jobs.validate_pulse import validate_pulse
from etf_engine.repositories.index_repository import IndexRepository

FETCHED_AT = datetime(2026, 9, 12, 18, 0)
BASE = date(2026, 3, 2)
DAYS = [BASE + timedelta(days=offset) for offset in range(40)]


def _meta() -> SourceMeta:
    return SourceMeta(source="test", fetched_at=FETCHED_AT, quality_status=QualityStatus.PASS)


def _prepare(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "database_path", tmp_path / "etf.duckdb")
    run_migrations()

    with connect(settings.database_path) as con:
        con.executemany(
            """
            INSERT INTO core.market_turnover_daily
                (trade_date, exchange, turnover_amount, float_market_cap, listing_count,
                 source, fetched_at, quality_status)
            VALUES (?, ?, ?, ?, ?, 'test', ?, 'PASS')
            """,
            [
                (day, exchange, 1.0e12, 5.0e13, 2000, FETCHED_AT)
                for day in DAYS
                for exchange in ("SSE", "SZSE")
            ],
        )
        con.executemany(
            """
            INSERT INTO core.margin_balance_daily
                (trade_date, exchange, margin_balance, source, fetched_at, quality_status)
            VALUES (?, ?, ?, 'test', ?, 'PASS')
            """,
            [(day, exchange, 1.0e12, FETCHED_AT) for day in DAYS for exchange in ("SSE", "SZSE")],
        )
        con.execute(
            """
            INSERT INTO core.market_activity_daily
                (trade_date, rising_count, falling_count, flat_count, limit_up_count,
                 source, fetched_at, quality_status)
            VALUES (?, 3000, 1000, 200, 50, 'test', ?, 'PASS')
            """,
            [DAYS[-1], FETCHED_AT],
        )
        con.executemany(
            """
            INSERT INTO mart.market_pulse_daily
                (trade_date, overall_state, liquidity_state, volume_state, etf_state,
                 broad_index_id, calculation_version, calculated_at)
            VALUES (?, ?, ?, ?, ?, '000300', 'pulse_v2', ?)
            """,
            [
                (day, "偏多" if index < 20 else "防守", "偏多", "偏多", "偏多", FETCHED_AT)
                for index, day in enumerate(DAYS)
            ],
        )
    IndexRepository().upsert_quotes(
        [
            IndexQuote(
                index_id="000300",
                trade_date=day,
                close=Decimal(4000 + index),
                source_meta=_meta(),
            )
            for index, day in enumerate(DAYS)
        ]
    )


def test_market_norm_computes_ratios(tmp_path, monkeypatch):
    _prepare(tmp_path, monkeypatch)

    result = compute_market_norm()

    assert result["rows_written"] == 40
    with connect(settings.database_path) as con:
        row = con.execute(
            """
            SELECT margin_balance_ratio, turnover_ratio, advance_ratio, limit_up_ratio
            FROM mart.market_norm_daily WHERE trade_date = ?
            """,
            [DAYS[-1]],
        ).fetchone()
    # 两融 2e12 / 流通市值 1e14 = 0.02；成交额 2e12 / 1e14 = 0.02
    assert row[0] == pytest.approx(0.02)
    assert row[1] == pytest.approx(0.02)
    assert row[2] == pytest.approx(3000 / 4000)
    assert row[3] == pytest.approx(50 / 4200)


def test_market_norm_leaves_fields_null_when_components_are_missing(tmp_path, monkeypatch):
    """只有一边交易所的两融数据时，分子不可信 → NULL，不拿单边数据顶。"""
    _prepare(tmp_path, monkeypatch)
    with connect(settings.database_path) as con:
        con.execute("DELETE FROM core.margin_balance_daily WHERE exchange = 'SZSE'")

    compute_market_norm()

    with connect(settings.database_path) as con:
        row = con.execute(
            "SELECT margin_balance_ratio, turnover_ratio FROM mart.market_norm_daily "
            "WHERE trade_date = ?",
            [DAYS[-1]],
        ).fetchone()
    assert row[0] is None, "单边两融 → NULL"
    assert row[1] is not None, "成交额不受影响"


def test_validate_pulse_reports_state_mix_and_forward_returns(tmp_path, monkeypatch):
    _prepare(tmp_path, monkeypatch)

    result = validate_pulse()

    assert result["status"] == "SUCCESS"
    assert result["days"] == 40
    states = {item["state"]: item for item in result["states"]}
    assert states["偏多"]["days"] == 20
    assert states["防守"]["days"] == 20
    assert result["switch_count"] == 1
    # 升级方案 §19：daily 与 transition 两套样本必须同时给出
    assert result["daily_sample_count"] >= result["transition_sample_count"]
    assert result["transition_sample_count"] > 0
    # 升级方案 §18：按预先固定的 regime（自然年）切片
    assert [item["label"] for item in result["regimes"]] == ["2026"]
    assert result["regimes"][0]["days"] == 40


def test_validate_pulse_writes_the_document(tmp_path, monkeypatch):
    _prepare(tmp_path, monkeypatch)
    target = tmp_path / "REGIME_VALIDATION.md"

    result = validate_pulse(write_doc=True, doc_path=target)

    assert result["doc_path"] == str(target)
    text = target.read_text(encoding="utf-8")
    assert "覆盖交易日" in text
    assert "daily 样本" in text
    assert "transition 样本" in text
    assert "## 4. 分 regime 视图" in text
    assert "阈值优化被明确排除" in text


def test_validate_pulse_counts_the_overall_unknown_state(tmp_path, monkeypatch):
    """``overall_state`` 的"数据不足"就是 UNKNOWN；不能拿 LayerState 的标签去匹配。

    匹配错了会出现两个错：UNKNOWN 占比永远是 0%，且"数据不足"被当成一个
    真实状态参与后续收益统计。
    """
    _prepare(tmp_path, monkeypatch)
    with connect(settings.database_path) as con:
        con.execute(
            """
            UPDATE mart.market_pulse_daily SET overall_state = '数据不足'
            WHERE trade_date >= ?
            """,
            [DAYS[-3]],
        )

    result = validate_pulse()

    assert result["unknown_ratio"] == pytest.approx(3 / 40)
    unknown = next(item for item in result["states"] if item["state"] == "数据不足")
    assert unknown["days"] == 3
