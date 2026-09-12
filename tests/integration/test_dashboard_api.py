from datetime import date, datetime
from decimal import Decimal

from fastapi.testclient import TestClient

from etf_engine.api import app as api_module
from etf_engine.config.settings import settings
from etf_engine.db.migrate import run_migrations
from etf_engine.domain.enums import QualityStatus
from etf_engine.domain.models import ETFQuote, SourceMeta
from etf_engine.repositories.quote_repository import QuoteRepository


def _quote(security_id: str, name: str) -> ETFQuote:
    return ETFQuote(
        security_id=security_id,
        trade_date=date(2026, 8, 13),
        name=name,
        close=Decimal("1.234"),
        change_pct=Decimal("2.5"),
        turnover_amount=Decimal("120000000"),
        source_meta=SourceMeta(
            source="test",
            fetched_at=datetime(2026, 8, 13, 15, 0),
            quality_status=QualityStatus.PASS,
        ),
    )


def test_dashboard_returns_an_honest_empty_state(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "database_path", tmp_path / "etf.duckdb")
    run_migrations()

    response = TestClient(api_module.app).get("/api/v1/dashboard")

    assert response.status_code == 200
    assert response.json()["data"] == {
        "etf_count": 0,
        "latest_trade_date": None,
        "total_turnover_amount": None,
        "stale_etf_count": 0,
    }


def test_dashboard_search_and_detail_return_latest_local_quotes(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "database_path", tmp_path / "etf.duckdb")
    run_migrations()
    QuoteRepository().upsert_many([_quote("588200.SH", "科创芯片ETF")])
    client = TestClient(api_module.app)

    overview = client.get("/api/v1/dashboard").json()
    search = client.get("/api/v1/etfs", params={"query": "芯片"}).json()
    detail = client.get("/api/v1/etfs/588200.SH").json()

    assert overview["data"]["etf_count"] == 1
    assert overview["meta"]["asof_date"] == "2026-08-13"
    assert search["data"][0]["security_id"] == "588200.SH"
    assert detail["data"]["quote"]["name"] == "科创芯片ETF"


def test_dashboard_page_and_sync_action_are_available(monkeypatch):
    monkeypatch.setattr(
        api_module,
        "sync_quotes",
        lambda: {"rows_fetched": 1, "rows_written": 1, "rows_rejected": 0},
    )
    client = TestClient(api_module.app)

    page = client.get("/")
    sync = client.post("/api/v1/sync/quotes")

    assert page.status_code == 200
    assert "ETF Lens" in page.text
    assert "核心研究指标" in page.text
    assert sync.status_code == 200
    assert sync.json()["data"]["rows_written"] == 1
