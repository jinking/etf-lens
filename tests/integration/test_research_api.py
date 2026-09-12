from datetime import date, datetime
from decimal import Decimal

from fastapi.testclient import TestClient
from typer.testing import CliRunner

from etf_engine.api import app as api_module
from etf_engine.cli.app import app as cli_app
from etf_engine.config.settings import settings
from etf_engine.db.migrate import run_migrations
from etf_engine.domain.enums import QualityStatus
from etf_engine.domain.models import ETFMaster, ETFQuote, ETFShare, SourceMeta
from etf_engine.repositories.master_repository import MasterRepository
from etf_engine.repositories.quote_repository import QuoteRepository
from etf_engine.repositories.share_repository import ShareRepository


def _meta() -> SourceMeta:
    return SourceMeta(
        source="test",
        fetched_at=datetime(2026, 9, 11, 15, 0),
        quality_status=QualityStatus.PASS,
    )


def test_compare_and_screen_api_and_cli(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "database_path", tmp_path / "etf.duckdb")
    run_migrations()

    master_repo = MasterRepository()
    quote_repo = QuoteRepository()
    share_repo = ShareRepository()

    master_repo.upsert_many(
        [
            ETFMaster(
                security_id="588200.SH",
                ticker="588200",
                exchange="SSE",
                fund_name="嘉实上证科创板芯片ETF",
                short_name="科创芯片ETF",
                fund_type="ETF",
                manager_name="嘉实基金管理有限公司",
                source_meta=_meta(),
            ),
            ETFMaster(
                security_id="159915.SZ",
                ticker="159915",
                exchange="SZSE",
                fund_name="易方达创业板ETF",
                short_name="创业板ETF",
                fund_type="ETF",
                manager_name="易方达基金管理有限公司",
                source_meta=_meta(),
            ),
        ]
    )

    quote_repo.upsert_many(
        [
            ETFQuote(
                security_id="588200.SH",
                trade_date=date(2026, 9, 11),
                name="科创芯片ETF",
                close=Decimal("1.25"),
                change_pct=Decimal("2.1"),
                turnover_amount=Decimal("1500000000"),
                source_meta=_meta(),
            ),
            ETFQuote(
                security_id="159915.SZ",
                trade_date=date(2026, 9, 11),
                name="创业板ETF",
                close=Decimal("3.30"),
                change_pct=Decimal("-0.5"),
                turnover_amount=Decimal("3000000000"),
                source_meta=_meta(),
            ),
        ]
    )

    share_repo.upsert_many(
        [
            ETFShare(
                security_id="588200.SH",
                trade_date=date(2026, 9, 11),
                shares=Decimal("1000000000"),
                nav=Decimal("1.25"),
                source_meta=_meta(),
            ),
            ETFShare(
                security_id="159915.SZ",
                trade_date=date(2026, 9, 11),
                shares=Decimal("2000000000"),
                nav=Decimal("3.30"),
                source_meta=_meta(),
            ),
        ]
    )

    client = TestClient(api_module.app)

    # 1. 触发计算 Mart
    compute_resp = client.post("/api/v1/compute/mart")
    assert compute_resp.status_code == 200
    assert compute_resp.json()["data"]["target_count"] == 2

    # 2. Compare API 测试
    compare_resp = client.get("/api/v1/research/compare", params={"security_ids": "588200.SH,159915.SZ"})
    assert compare_resp.status_code == 200
    comp_data = compare_resp.json()["data"]
    assert len(comp_data) == 2
    ids = [item["security_id"] for item in comp_data]
    assert "588200.SH" in ids
    assert "159915.SZ" in ids

    # 3. Screen API 测试（筛选规模大于 20 亿的 ETF）
    screen_resp = client.get("/api/v1/research/screen", params={"min_aum": 2000000000})
    assert screen_resp.status_code == 200
    screened = screen_resp.json()["data"]
    assert len(screened) == 1
    assert screened[0]["security_id"] == "159915.SZ"

    # 4. CLI 测试
    runner = CliRunner()
    cli_comp = runner.invoke(cli_app, ["compare", "588200.SH", "159915.SZ"])
    assert cli_comp.exit_code == 0
    assert "588200.SH" in cli_comp.stdout
    assert "159915.SZ" in cli_comp.stdout

    cli_screen = runner.invoke(cli_app, ["screen", "--min-aum", "2000000000"])
    assert cli_screen.exit_code == 0
    assert "159915.SZ" in cli_screen.stdout
