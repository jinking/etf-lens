"""Point-in-Time：查历史日期时绝不能读到当天之后的数据。"""

from datetime import date, timedelta
from decimal import Decimal

from etf_engine.config.settings import settings
from etf_engine.db.connection import connect
from etf_engine.db.migrate import run_migrations
from etf_engine.domain.enums import QualityStatus
from etf_engine.domain.models import ETFMaster, ETFQuote, ETFShare, SourceMeta
from etf_engine.domain.research_context import ResearchContext
from etf_engine.repositories.master_repository import MasterRepository
from etf_engine.repositories.quote_repository import QuoteRepository
from etf_engine.repositories.share_repository import ShareRepository
from etf_engine.repositories.trading_calendar_repository import TradingCalendarRepository
from etf_engine.services.research_service import ResearchService

SECURITY_ID = "510300.SH"
D1, D2, D3 = date(2026, 9, 9), date(2026, 9, 10), date(2026, 9, 11)
FETCHED_AT = __import__("datetime").datetime(2026, 9, 12, 18, 0)


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
                security_id=SECURITY_ID,
                ticker="510300",
                exchange="SSE",
                fund_name="沪深300ETF",
                source_meta=_meta(),
            )
        ]
    )
    QuoteRepository().upsert_many(
        [
            ETFQuote(
                security_id=SECURITY_ID,
                trade_date=day,
                close=Decimal(str(close)),
                turnover_amount=Decimal(str(close * 1000)),
                source_meta=_meta(),
            )
            for day, close in ((D1, 100), (D2, 110), (D3, 120))
        ]
    )
    ShareRepository().upsert_many(
        [
            ETFShare(
                security_id=SECURITY_ID,
                trade_date=day,
                shares=Decimal(str(shares)),
                nav=Decimal("1.5"),
                source_meta=_meta(),
            )
            for day, shares in ((D1, 1000), (D2, 1100), (D3, 1200))
        ]
    )


def test_compare_asof_never_reads_future_rows(tmp_path, monkeypatch):
    _prepare(tmp_path, monkeypatch)

    rows = ResearchService().compare([SECURITY_ID], ResearchContext(asof_date=D2))

    row = rows[0]
    assert row["close"] == 110.0, "asof=09-10 时不能看到 09-11 的 120"
    assert row["shares"] == 1100.0
    assert row["quote_asof_date"] == D2.isoformat()
    assert row["share_asof_date"] == D2.isoformat()
    assert row["research_asof_date"] == D2.isoformat()
    # 这个夹具没有跑 compute_mart，因此 metric / flow 两块缺失 → PARTIAL
    assert row["data_quality"] == "PARTIAL"
    assert row["stale_blocks"] == ["metric:missing", "flow:missing"]


def test_compare_asof_on_a_date_without_data_falls_back_to_earlier_days(tmp_path, monkeypatch):
    _prepare(tmp_path, monkeypatch)
    weekend = date(2026, 9, 12)  # 周六，没有数据

    row = ResearchService().compare([SECURITY_ID], ResearchContext(asof_date=weekend))[0]

    assert row["quote_asof_date"] == D3.isoformat()
    assert row["quote_staleness_days"] == 1
    assert row["close"] == 120.0


def test_max_staleness_nulls_old_blocks_instead_of_mixing_dates(tmp_path, monkeypatch):
    _prepare(tmp_path, monkeypatch)
    # 份额只到 09-09（落后 2 天），行情到 09-11
    with connect(settings.database_path) as con:
        con.execute("DELETE FROM core.etf_share_daily WHERE trade_date > ?", [D1])

    row = ResearchService().compare(
        [SECURITY_ID], ResearchContext(asof_date=D3, max_staleness_days=0)
    )[0]

    assert row["close"] == 120.0
    assert row["shares"] is None, "份额过期 → 置空，不用旧值冒充当天"
    assert row["estimated_aum"] is None
    assert row["share_staleness_days"] == 2
    assert "share:stale" in row["stale_blocks"]
    assert row["data_quality"] == "PARTIAL"


def test_require_same_trade_date_keeps_only_aligned_blocks(tmp_path, monkeypatch):
    _prepare(tmp_path, monkeypatch)
    with connect(settings.database_path) as con:
        con.execute("DELETE FROM core.etf_quote_daily WHERE trade_date > ?", [D2])

    row = ResearchService().compare(
        [SECURITY_ID],
        ResearchContext(asof_date=D3, require_same_trade_date=True),
    )[0]

    # 09-11 只有份额、没有行情 → 行情块被拒绝，份额保留
    assert row["close"] is None
    assert row["turnover_amount"] is None
    assert row["shares"] == 1200.0
    assert "quote:not_same_trade_date" in row["stale_blocks"]


def test_latest_mode_still_reports_each_block_asof(tmp_path, monkeypatch):
    _prepare(tmp_path, monkeypatch)

    row = ResearchService().compare([SECURITY_ID])[0]

    assert row["research_asof_date"] is None, "最新模式没有 as-of"
    assert row["quote_asof_date"] == D3.isoformat()
    assert row["quote_staleness_days"] is None, "最新模式不判新鲜度"
    assert "quote:missing" not in row["stale_blocks"]
