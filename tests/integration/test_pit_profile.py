"""基金档案 PIT：观测时间晚于 as-of 的档案字段对它不可用。"""

from datetime import date

from etf_engine.config.settings import settings
from etf_engine.db.connection import connect
from etf_engine.db.migrate import run_migrations
from etf_engine.domain.research_context import ResearchContext
from etf_engine.services.research_service import ResearchService

PROFILE_OBSERVED_AT = "2026-09-12 18:00:00"
ASOF_BEFORE = date(2026, 6, 1)
#: 档案观测时间之后的某天：只有到这时费率才对研究可见。
ASOF_AFTER = date(2026, 9, 13)


def _prepare(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "database_path", tmp_path / "etf.duckdb")
    run_migrations()
    with connect(settings.database_path) as con:
        con.execute(
            """
            INSERT INTO core.etf_master (
                security_id, ticker, exchange, fund_name, management_fee_pct,
                profile_observed_at
            ) VALUES ('510300.SH', '510300', 'SSE', '沪深300ETF', 0.15, CAST(? AS TIMESTAMP))
            """,
            [PROFILE_OBSERVED_AT],
        )
        con.execute(
            """
            INSERT INTO core.etf_quote_daily
                (security_id, trade_date, close, source, fetched_at, quality_status)
            VALUES ('510300.SH', ?, 4.5, 'test', CAST(? AS TIMESTAMP), 'PASS')
            """,
            [date(2026, 9, 11), PROFILE_OBSERVED_AT],
        )


def test_profile_field_is_hidden_before_it_was_observed(tmp_path, monkeypatch):
    _prepare(tmp_path, monkeypatch)

    row = ResearchService().compare(["510300.SH"], ResearchContext(asof_date=ASOF_BEFORE))[0]

    assert row["management_fee_pct"] is None, "9 月才观测到的费率，6 月不可见"


def test_profile_field_is_visible_after_observation(tmp_path, monkeypatch):
    _prepare(tmp_path, monkeypatch)

    row = ResearchService().compare(["510300.SH"], ResearchContext(asof_date=ASOF_AFTER))[0]

    assert row["management_fee_pct"] == 0.15
