"""Screener 的 as-of 纪律：筛选条件只能使用当时可见的数据。"""

from datetime import date, datetime, timedelta
from decimal import Decimal

from etf_engine.config.settings import settings
from etf_engine.db.connection import connect
from etf_engine.db.migrate import run_migrations
from etf_engine.domain.enums import QualityStatus
from etf_engine.domain.models import ETFMaster, ETFQuote, ETFShare, SourceMeta
from etf_engine.domain.research_context import ResearchContext
from etf_engine.jobs.compute_mart import compute_mart
from etf_engine.repositories.master_repository import MasterRepository
from etf_engine.repositories.quote_repository import QuoteRepository
from etf_engine.repositories.share_repository import ShareRepository
from etf_engine.repositories.trading_calendar_repository import TradingCalendarRepository
from etf_engine.services.research_service import ResearchService

FETCHED_AT = datetime(2026, 9, 12, 18, 0)
D1, D2 = date(2026, 9, 9), date(2026, 9, 10)
D3 = date(2026, 9, 11)


def _meta() -> SourceMeta:
    return SourceMeta(source="test", fetched_at=FETCHED_AT, quality_status=QualityStatus.PASS)


def _prepare(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "database_path", tmp_path / "etf.duckdb")
    run_migrations()
    base = date(2026, 1, 1)
    TradingCalendarRepository().upsert_many(
        [
            base + timedelta(days=offset)
            for offset in range(365)
            if (base + timedelta(days=offset)).weekday() < 5
        ],
        source="test",
        upstream_source="test",
    )
    MasterRepository().upsert_many(
        [
            ETFMaster(
                security_id="510300.SH",
                ticker="510300",
                exchange="SSE",
                fund_name="沪深300ETF",
                source_meta=_meta(),
            ),
            ETFMaster(
                security_id="159919.SZ",
                ticker="159919",
                exchange="SZSE",
                fund_name="沪深300ETF深",
                source_meta=_meta(),
            ),
        ]
    )
    QuoteRepository().upsert_many(
        [
            ETFQuote(
                security_id=security_id,
                trade_date=day,
                close=Decimal(str(close)),
                turnover_amount=Decimal(str(close * 10_000)),
                source_meta=_meta(),
            )
            for security_id, day, close in (
                ("510300.SH", D1, 100),
                ("510300.SH", D2, 110),
                ("510300.SH", D3, 120),
                ("159919.SZ", D1, 50),
                ("159919.SZ", D2, 50),
                ("159919.SZ", D3, 50),
            )
        ]
    )
    ShareRepository().upsert_many(
        [
            ETFShare(
                security_id=security_id,
                trade_date=day,
                shares=Decimal(str(aum)),
                nav=Decimal("1.0"),
                source_meta=_meta(),
            )
            for security_id, day, aum in (
                # 510300 在 09-11 规模跳到 1e9；09-10 只有 100
                ("510300.SH", D1, 100),
                ("510300.SH", D2, 100),
                ("510300.SH", D3, 1_000_000_000),
                ("159919.SZ", D1, 500),
                ("159919.SZ", D2, 500),
                ("159919.SZ", D3, 500),
            )
        ]
    )
    compute_mart()


def test_screen_asof_uses_only_data_visible_then(tmp_path, monkeypatch):
    """09-11 才出现的规模不能影响 asof=09-10 的筛选结果。"""
    _prepare(tmp_path, monkeypatch)

    rows = ResearchService().screen(min_aum=1_000_000, context=ResearchContext(asof_date=D2))

    assert rows == [], "09-10 当时两只 ETF 的规模都只有几百，不该通过 100 万门槛"


def test_screen_asof_sees_the_later_value_when_it_is_visible(tmp_path, monkeypatch):
    _prepare(tmp_path, monkeypatch)

    rows = ResearchService().screen(min_aum=1_000_000, context=ResearchContext(asof_date=D3))

    assert [row["security_id"] for row in rows] == ["510300.SH"]
    assert rows[0]["aum"] == 1_000_000_000.0
    assert rows[0]["research_asof_date"] == D3.isoformat()
    assert rows[0]["share_asof_date"] == D3.isoformat()


def test_screen_does_not_let_stale_blocks_pass_filters(tmp_path, monkeypatch):
    """份额过期被置空后，不能靠"旧值"满足规模条件。"""
    _prepare(tmp_path, monkeypatch)
    with connect(settings.database_path) as con:
        con.execute("DELETE FROM core.etf_share_daily WHERE trade_date = ?", [D3])

    rows = ResearchService().screen(
        min_aum=1_000_000,
        context=ResearchContext(asof_date=D3, max_staleness_days=0),
    )

    assert rows == []


def test_screen_still_filters_by_tag_and_query(tmp_path, monkeypatch):
    _prepare(tmp_path, monkeypatch)

    by_query = ResearchService().screen(query="159919", context=ResearchContext(asof_date=D3))
    by_missing_tag = ResearchService().screen(tag="半导体", context=ResearchContext(asof_date=D3))

    assert [row["security_id"] for row in by_query] == ["159919.SZ"]
    assert by_missing_tag == []


def test_screen_ordering_prefers_turnover_then_aum(tmp_path, monkeypatch):
    _prepare(tmp_path, monkeypatch)

    rows = ResearchService().screen(context=ResearchContext(asof_date=D3))

    # 510300 成交额 1_200_000 > 159919 的 500_000
    assert [row["security_id"] for row in rows] == ["510300.SH", "159919.SZ"]
