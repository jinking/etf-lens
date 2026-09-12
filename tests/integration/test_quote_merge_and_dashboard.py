"""行情写入必须按列合并，且看板口径必须只覆盖同一交易日。"""

from datetime import date, datetime
from decimal import Decimal

from fastapi.testclient import TestClient

from etf_engine.api import app as api_module
from etf_engine.config.settings import settings
from etf_engine.db.connection import connect
from etf_engine.db.migrate import run_migrations
from etf_engine.domain.enums import QualityStatus
from etf_engine.domain.models import ETFMaster, ETFQuote, SourceMeta
from etf_engine.repositories.master_repository import MasterRepository
from etf_engine.repositories.quote_repository import QuoteRepository

FETCHED_AT = datetime(2026, 9, 12, 10, 0)


def _meta(upstream: str) -> SourceMeta:
    return SourceMeta(
        source="test",
        upstream_source=upstream,
        fetched_at=FETCHED_AT,
        quality_status=QualityStatus.PASS,
    )


def _spot_quote(security_id: str, name: str, trade_date: date) -> ETFQuote:
    return ETFQuote(
        security_id=security_id,
        trade_date=trade_date,
        name=name,
        open=Decimal("1.000"),
        high=Decimal("1.100"),
        low=Decimal("0.990"),
        close=Decimal("1.050"),
        prev_close=Decimal("1.000"),
        change=Decimal("0.050"),
        change_pct=Decimal("5.00"),
        turnover_rate=Decimal("1.20"),
        turnover_amount=Decimal("100000000"),
        iopv=Decimal("1.040"),
        premium_discount_pct=Decimal("0.0096"),
        premium_discount_pct_normalized=Decimal("0.0096"),
        bid1=Decimal("1.049"),
        ask1=Decimal("1.051"),
        source_meta=_meta("eastmoney"),
    )


def _history_quote(security_id: str, trade_date: date) -> ETFQuote:
    """历史回补来源（新浪）没有名称、IOPV、买卖盘和资金流。"""
    return ETFQuote(
        security_id=security_id,
        trade_date=trade_date,
        open=Decimal("1.010"),
        high=Decimal("1.110"),
        low=Decimal("0.980"),
        close=Decimal("1.060"),
        volume=Decimal("12345"),
        turnover_amount=Decimal("110000000"),
        source_meta=_meta("sina"),
    )


def test_history_backfill_does_not_erase_snapshot_columns(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "database_path", tmp_path / "etf.duckdb")
    run_migrations()
    repository = QuoteRepository()
    trade_date = date(2026, 9, 11)

    repository.upsert_many([_spot_quote("588200.SH", "科创芯片ETF", trade_date)])
    repository.upsert_many([_history_quote("588200.SH", trade_date)])

    row = repository.get_latest("588200.SH")

    assert row["close"] == 1.06, "OHLCV 由后写入的来源修正"
    assert row["turnover_amount"] == 110_000_000
    assert row["name"] == "科创芯片ETF", "历史来源没有名称，不能把已有名称覆盖成 NULL"
    assert row["iopv"] == 1.04
    assert row["bid1"] == 1.049
    assert row["prev_close"] == 1.0
    assert row["premium_discount_pct_normalized"] == 0.0096


def test_snapshot_after_backfill_still_keeps_the_latest_facts(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "database_path", tmp_path / "etf.duckdb")
    run_migrations()
    repository = QuoteRepository()
    trade_date = date(2026, 9, 11)

    repository.upsert_many([_history_quote("588200.SH", trade_date)])
    repository.upsert_many([_spot_quote("588200.SH", "科创芯片ETF", trade_date)])

    row = repository.get_latest("588200.SH")

    assert row["close"] == 1.05
    assert row["name"] == "科创芯片ETF"
    assert row["upstream_source"] == "eastmoney"


def test_search_and_detail_fall_back_to_master_name(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "database_path", tmp_path / "etf.duckdb")
    run_migrations()
    MasterRepository().upsert_many(
        [
            ETFMaster(
                security_id="588200.SH",
                ticker="588200",
                exchange="SSE",
                fund_name="嘉实上证科创板芯片ETF",
                short_name="科创芯片ETF",
                source_meta=_meta("test"),
            )
        ]
    )
    quote_repository = QuoteRepository()
    quote_repository.upsert_many([_history_quote("588200.SH", date(2026, 9, 11))])

    assert quote_repository.get_latest("588200.SH")["name"] == "科创芯片ETF"
    assert quote_repository.search_latest()[0]["name"] == "科创芯片ETF"
    assert quote_repository.search_latest(query="科创")[0]["security_id"] == "588200.SH"


def test_dashboard_only_aggregates_the_latest_trading_day(tmp_path, monkeypatch):
    """看板不能把 08-13 的快照和 09-11 的历史行加在一起。"""
    monkeypatch.setattr(settings, "database_path", tmp_path / "etf.duckdb")
    run_migrations()
    repository = QuoteRepository()
    repository.upsert_many([_history_quote("588200.SH", date(2026, 8, 13))])
    repository.upsert_many([_history_quote("159915.SZ", date(2026, 9, 11))])

    with connect(settings.database_path) as con:
        con.execute(
            """
            UPDATE core.etf_quote_daily SET turnover_amount = CASE
                WHEN security_id = '588200.SH' THEN 1000 ELSE 7 END
            """
        )

    response = TestClient(api_module.app).get("/api/v1/dashboard")
    body = response.json()

    assert body["meta"]["asof_date"] == "2026-09-11"
    assert body["data"]["etf_count"] == 1
    assert body["data"]["total_turnover_amount"] == 7
    assert body["data"]["stale_etf_count"] == 1
