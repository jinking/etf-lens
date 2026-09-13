"""Screener AUM PIT 回退测试。

COALESCE(s.estimated_aum, m.reported_aum) 中，reported_aum 只有在
profile_observed_at <= asof 时才可 fallback，否则返回 NULL。
"""

from datetime import date, datetime
from decimal import Decimal

from etf_engine.config.settings import settings
from etf_engine.db.connection import connect
from etf_engine.db.migrate import run_migrations
from etf_engine.domain.enums import QualityStatus
from etf_engine.domain.models import ETFMaster, ETFQuote, SourceMeta
from etf_engine.domain.research_context import ResearchContext
from etf_engine.repositories.master_repository import MasterRepository
from etf_engine.repositories.quote_repository import QuoteRepository
from etf_engine.repositories.trading_calendar_repository import TradingCalendarRepository
from etf_engine.services.research_service import ResearchService

SECURITY_ID = "510300.SH"
T1 = date(2026, 9, 1)
T2 = date(2026, 9, 15)
FETCHED_AT = datetime(2026, 9, 15, 10, 0)


def _meta() -> SourceMeta:
    return SourceMeta(source="test", fetched_at=FETCHED_AT, quality_status=QualityStatus.PASS)


def test_screener_aum_cannot_fallback_to_unobserved_reported_aum(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "database_path", tmp_path / "etf.duckdb")
    run_migrations()
    TradingCalendarRepository().upsert_many([T1, T2], source="test", upstream_source="test")

    MasterRepository().upsert_many(
        [
            ETFMaster(
                security_id=SECURITY_ID,
                ticker="510300",
                exchange="SSE",
                fund_name="300ETF",
                reported_aum=Decimal("9999999.0"),
                source_meta=_meta(),
            )
        ]
    )
    QuoteRepository().upsert_many(
        [
            ETFQuote(
                security_id=SECURITY_ID,
                trade_date=T1,
                close=Decimal("1.0"),
                turnover_amount=Decimal("100000"),
                source_meta=_meta(),
            )
        ]
    )

    # 1. 档案在 T2 才观测，T1 查 screener：reported_aum 不得作为 AUM fallback
    with connect(settings.database_path) as con:
        con.execute(
            "UPDATE core.etf_master SET profile_observed_at = ? WHERE security_id = ?",
            [datetime(2026, 9, 15, 0, 0), SECURITY_ID],
        )

    rows_t1 = ResearchService().screen(context=ResearchContext(asof_date=T1))
    assert len(rows_t1) == 1
    assert rows_t1[0]["aum"] is None, (
        f"T1 查询时档案在 T2 才观测，aum 必须为 NULL，实际: {rows_t1[0]['aum']}"
    )

    # 2. 档案在 T1（或更早）已观测，T1 查 screener：允许 fallback reported_aum
    with connect(settings.database_path) as con:
        con.execute(
            "UPDATE core.etf_master SET profile_observed_at = ? WHERE security_id = ?",
            [datetime(2026, 9, 1, 0, 0), SECURITY_ID],
        )

    rows_t1_observed = ResearchService().screen(context=ResearchContext(asof_date=T1))
    assert len(rows_t1_observed) == 1
    assert rows_t1_observed[0]["aum"] == 9999999.0
