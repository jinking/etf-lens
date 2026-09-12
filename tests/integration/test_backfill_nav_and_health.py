"""净值历史回补、源健康度与多源对账。"""

from datetime import date, datetime, timedelta
from decimal import Decimal

from etf_engine.config.settings import settings
from etf_engine.db.connection import connect
from etf_engine.db.migrate import run_migrations
from etf_engine.domain.enums import QualityStatus
from etf_engine.domain.models import ETFNav, ETFQuote, ETFShare, SourceMeta
from etf_engine.ingestion.source_health import track_source_health
from etf_engine.jobs.backfill_history import backfill_history
from etf_engine.jobs.backfill_nav import backfill_nav
from etf_engine.jobs.compute_mart import compute_mart
from etf_engine.repositories.quote_repository import QuoteRepository
from etf_engine.repositories.share_repository import ShareRepository
from etf_engine.repositories.trading_calendar_repository import TradingCalendarRepository
from etf_engine.sources.registry import registry

FETCHED_AT = datetime(2026, 9, 12, 10, 0)


def _meta(upstream: str) -> SourceMeta:
    return SourceMeta(
        source="test",
        upstream_source=upstream,
        fetched_at=FETCHED_AT,
        quality_status=QualityStatus.PASS,
    )


def _seed_calendar() -> None:
    base = date(2026, 1, 1)
    days = [
        base + timedelta(days=offset)
        for offset in range(365)
        if (base + timedelta(days=offset)).weekday() < 5
    ]
    TradingCalendarRepository().upsert_many(days, source="test", upstream_source="test")


def _prepare(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "database_path", tmp_path / "etf.duckdb")
    monkeypatch.setattr(settings, "raw_path", tmp_path / "raw")
    run_migrations()
    _seed_calendar()
    ShareRepository().upsert_many(
        [
            ETFShare(
                security_id="588200.SH",
                trade_date=date(2026, 9, 11),
                shares=Decimal("1000"),
                nav=Decimal("1.0913"),
                source_meta=_meta("sse"),
            )
        ]
    )


class _FakeNavHistorySource:
    """按基金返回一段净值历史，模拟逐只基金接口。"""

    days = 30
    calls: list[str] = []

    def fetch_nav_history_with_issues(self, security_id, start_date, end_date):
        type(self).calls.append(security_id)
        navs = [
            ETFNav(
                security_id=security_id,
                nav_date=date(2026, 8, 31) + timedelta(days=offset),
                unit_nav=Decimal("1.10") + Decimal(offset) / 1000,
                source_meta=_meta("eastmoney"),
            )
            for offset in range(type(self).days)
            if (date(2026, 8, 31) + timedelta(days=offset)).weekday() < 5
        ]
        return navs, []


def test_backfill_nav_targets_funds_missing_history_and_writes_rows(tmp_path, monkeypatch):
    _prepare(tmp_path, monkeypatch)
    _FakeNavHistorySource.calls = []
    monkeypatch.setattr(type(registry), "nav_history_source", _FakeNavHistorySource, raising=False)

    result = backfill_nav(days=20, limit=5, sleep_seconds=0)

    assert result["target_count"] == 1
    assert result["funds_fetched"] == 1
    assert result["rows_written"] > 10
    assert _FakeNavHistorySource.calls == ["588200.SH"]

    with connect(settings.database_path) as con:
        health = con.execute(
            "SELECT status, consecutive_failures FROM ops.source_health"
        ).fetchall()
    assert health == [("OK", 0)], "源健康度必须被写入"


def test_backfill_nav_skips_when_history_is_complete(tmp_path, monkeypatch):
    _prepare(tmp_path, monkeypatch)
    monkeypatch.setattr(type(registry), "nav_history_source", _FakeNavHistorySource, raising=False)
    backfill_nav(days=20, limit=5, sleep_seconds=0)

    again = backfill_nav(days=20, limit=5, sleep_seconds=0)

    assert again["status"] == "SKIPPED"


def test_backfill_nav_survives_a_single_fund_failure(tmp_path, monkeypatch):
    _prepare(tmp_path, monkeypatch)

    class _Flaky(_FakeNavHistorySource):
        def fetch_nav_history_with_issues(self, security_id, start_date, end_date):
            raise RuntimeError("upstream broke")

    monkeypatch.setattr(type(registry), "nav_history_source", _Flaky, raising=False)

    result = backfill_nav(days=20, limit=5, sleep_seconds=0)

    assert result["status"] == "FAILED"
    assert result["funds_failed"] == 1
    with connect(settings.database_path) as con:
        error_issues = con.execute(
            "SELECT count(*) FROM ops.quality_issue WHERE rule_name = 'nav_history_fetch_failed'"
        ).fetchone()[0]
        health = con.execute(
            "SELECT status, consecutive_failures FROM ops.source_health"
        ).fetchone()
    assert error_issues == 1
    assert health == ("FAILED", 1)


def test_source_health_counts_consecutive_failures(tmp_path, monkeypatch):
    _prepare(tmp_path, monkeypatch)

    for _ in range(3):
        try:
            with track_source_health("sse", "etf_share"):
                raise ConnectionError("boom")
        except ConnectionError:
            pass

    with connect(settings.database_path) as con:
        row = con.execute(
            "SELECT status, consecutive_failures FROM ops.source_health "
            "WHERE source = 'sse' AND capability = 'etf_share'"
        ).fetchone()
    assert row == ("FAILED", 3)

    with track_source_health("sse", "etf_share"):
        pass

    with connect(settings.database_path) as con:
        row = con.execute(
            "SELECT status, consecutive_failures, last_error FROM ops.source_health "
            "WHERE source = 'sse' AND capability = 'etf_share'"
        ).fetchone()
    assert row == ("OK", 0, None)


def test_history_backfill_refuses_to_silently_overwrite_a_conflicting_close(tmp_path, monkeypatch):
    """同一天、同为日收盘、但来源不同且差异超阈值：记 CONFLICT 且不覆盖。"""
    _prepare(tmp_path, monkeypatch)
    QuoteRepository().upsert_many(
        [
            ETFQuote(
                security_id="588200.SH",
                trade_date=date(2026, 9, 10),
                close=Decimal("1.000"),
                source_meta=_meta("sina"),
            )
        ]
    )

    class _ConflictingHistorySource:
        def fetch_history(self, security_id, start_date, end_date):
            return [
                ETFQuote(
                    security_id=security_id,
                    trade_date=date(2026, 9, 10),
                    close=Decimal("1.250"),  # 25% 差异，明显冲突
                    source_meta=_meta("eastmoney"),
                )
            ]

    monkeypatch.setattr(type(registry), "history_source", _ConflictingHistorySource, raising=False)

    result = backfill_history(security_ids=["588200.SH"], days=5)

    assert result["conflicts"] == 1
    assert result["rows_written"] == 0
    row = QuoteRepository().get_latest("588200.SH")
    assert row["close"] == 1.0, "冲突时保留已入库的值"
    with connect(settings.database_path) as con:
        issues = con.execute(
            "SELECT count(*) FROM ops.quality_issue WHERE rule_name = 'close_source_conflict'"
        ).fetchone()[0]
    assert issues == 1


def test_nav_history_unblocks_subscription_estimates(tmp_path, monkeypatch):
    """净值历史补齐后，估算申赎资金不再是 NULL。"""
    _prepare(tmp_path, monkeypatch)
    QuoteRepository().upsert_many(
        [
            ETFQuote(
                security_id="588200.SH",
                trade_date=date(2026, 8, 31) + timedelta(days=offset),
                close=Decimal("1.10"),
                source_meta=_meta("sina"),
            )
            for offset in range(30)
        ]
    )
    ShareRepository().upsert_many(
        [
            ETFShare(
                security_id="588200.SH",
                trade_date=date(2026, 8, 31) + timedelta(days=offset),
                shares=Decimal(1000 + offset * 10),
                source_meta=_meta("sse"),
            )
            for offset in range(30)
            if (date(2026, 8, 31) + timedelta(days=offset)).weekday() < 5
        ]
    )
    monkeypatch.setattr(type(registry), "nav_history_source", _FakeNavHistorySource, raising=False)
    backfill_nav(days=20, limit=5, sleep_seconds=0)

    compute_mart(security_ids=["588200.SH"])

    with connect(settings.database_path) as con:
        row = con.execute(
            """
            SELECT estimated_net_subscription_1d, estimated_net_subscription_5d
            FROM mart.etf_flow_daily WHERE security_id = '588200.SH'
            """
        ).fetchone()
    assert row[0] is not None
    assert row[1] is not None
