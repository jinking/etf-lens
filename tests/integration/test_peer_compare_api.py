"""同类比较端到端：分组 → 分位 → API/服务输出。"""

from datetime import date, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from etf_engine.api import app as api_module
from etf_engine.config.settings import settings
from etf_engine.db.connection import connect
from etf_engine.db.migrate import run_migrations
from etf_engine.domain.enums import QualityStatus
from etf_engine.domain.models import (
    ETFHolding,
    ETFMaster,
    ETFQuote,
    ETFShare,
    SourceMeta,
)
from etf_engine.jobs.compute_mart import compute_mart
from etf_engine.jobs.compute_peer_metrics import compute_peer_metrics
from etf_engine.repositories.holding_repository import HoldingRepository
from etf_engine.repositories.master_repository import MasterRepository
from etf_engine.repositories.quote_repository import QuoteRepository
from etf_engine.repositories.share_repository import ShareRepository
from etf_engine.repositories.trading_calendar_repository import TradingCalendarRepository
from etf_engine.services.peer_service import PeerService

FETCHED_AT = datetime(2026, 9, 12, 18, 0)
ASOF = date(2026, 9, 11)

#: 同一跟踪指数（000300）下的三只 ETF + 一只别的指数（样本不足，不给分位）。
UNIVERSE = {
    "510300.SH": {"index": "000300", "fee": Decimal("0.15"), "aum": 9_000.0},
    "510310.SH": {"index": "000300", "fee": Decimal("0.20"), "aum": 5_000.0},
    "159919.SZ": {"index": "000300", "fee": Decimal("0.50"), "aum": 1_000.0},
    "588200.SH": {"index": "931160", "fee": Decimal("0.50"), "aum": 800.0},
}


def _meta() -> SourceMeta:
    return SourceMeta(source="test", fetched_at=FETCHED_AT, quality_status=QualityStatus.PASS)


def _prepare(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "database_path", tmp_path / "etf.duckdb")
    run_migrations()
    base = date(2026, 1, 1)
    TradingCalendarRepository().upsert_many(
        [
            base + __import__("datetime").timedelta(days=offset)
            for offset in range(365)
            if (base + __import__("datetime").timedelta(days=offset)).weekday() < 5
        ],
        source="test",
        upstream_source="test",
    )
    MasterRepository().upsert_many(
        [
            ETFMaster(
                security_id=security_id,
                ticker=security_id.split(".")[0],
                exchange="SSE" if security_id.endswith("SH") else "SZSE",
                fund_name=f"{security_id} 基金",
                short_name=f"{security_id}ETF",
                management_fee_pct=spec["fee"],
                tracking_index_id=spec["index"],
                tracking_index_name="沪深300指数" if spec["index"] == "000300" else "芯片指数",
                source_meta=_meta(),
            )
            for security_id, spec in UNIVERSE.items()
        ]
    )
    QuoteRepository().upsert_many(
        [
            ETFQuote(
                security_id=security_id,
                trade_date=ASOF,
                name=f"{security_id}ETF",
                close=Decimal("1.0"),
                turnover_amount=Decimal(str(spec["aum"])),
                source_meta=_meta(),
            )
            for security_id, spec in UNIVERSE.items()
        ]
    )
    ShareRepository().upsert_many(
        [
            ETFShare(
                security_id=security_id,
                trade_date=ASOF,
                shares=Decimal(str(spec["aum"])),
                nav=Decimal("1.0"),
                source_meta=_meta(),
            )
            for security_id, spec in UNIVERSE.items()
        ]
    )
    HoldingRepository().upsert_many(
        [
            ETFHolding(
                etf_id="510300.SH",
                report_date=date(2026, 6, 30),
                stock_id="600519.SH",
                stock_name="贵州茅台",
                weight_pct=Decimal("5.0"),
                source_meta=_meta(),
            ),
            ETFHolding(
                etf_id="510310.SH",
                report_date=date(2026, 6, 30),
                stock_id="600519.SH",
                stock_name="贵州茅台",
                weight_pct=Decimal("4.0"),
                source_meta=_meta(),
            ),
        ]
    )
    from etf_engine.repositories.index_repository import IndexRepository

    IndexRepository().upsert_map(
        [
            {
                "etf_id": security_id,
                "index_id": spec["index"],
                "index_name": "沪深300指数" if spec["index"] == "000300" else "芯片指数",
                "valid_from": ASOF,
                "source": "test",
            }
            for security_id, spec in UNIVERSE.items()
        ]
    )
    with connect(settings.database_path) as con:
        con.execute(
            "UPDATE core.etf_master SET profile_observed_at = ?",
            [datetime(2026, 9, 11, 0, 0)],
        )

    compute_mart()


def test_peer_metrics_are_computed_per_tracking_index(tmp_path, monkeypatch):
    _prepare(tmp_path, monkeypatch)

    result = compute_peer_metrics(asof=ASOF)

    assert result["metrics_written"] == 3, "同一指数的三只 ETF 各得一行"
    assert result["skipped_small_groups"] == 1, "只有一只的组不给分位"

    with connect(settings.database_path) as con:
        rows = {
            row[0]: row
            for row in con.execute(
                """
                SELECT security_id, aum_rank_pct, fee_rank_pct, peer_count
                FROM mart.etf_peer_metric_daily ORDER BY security_id
                """
            ).fetchall()
        }
    # 规模最大 → 分位最高；费率最低 → 反向分位后也最高
    assert rows["510300.SH"][1] == pytest.approx(1.0)
    assert rows["159919.SZ"][1] == pytest.approx(0.0)
    assert rows["510300.SH"][2] == pytest.approx(1.0)
    assert rows["159919.SZ"][2] == pytest.approx(0.0)
    assert rows["510300.SH"][3] == 3


def test_peer_group_uses_the_tracking_index_not_the_name(tmp_path, monkeypatch):
    _prepare(tmp_path, monkeypatch)
    # 目录里登记了指数名 → 只有名称的 ETF 也能并到同一组
    from etf_engine.domain.models import IndexCatalogEntry
    from etf_engine.repositories.index_repository import IndexRepository

    IndexRepository().upsert_catalog(
        [
            IndexCatalogEntry(
                index_id="931160",
                index_name="芯片指数",
                source_meta=_meta(),
            )
        ]
    )
    compute_peer_metrics(asof=ASOF)

    with connect(settings.database_path) as con:
        rows = dict(
            con.execute("SELECT security_id, peer_group_id FROM mart.etf_peer_group").fetchall()
        )

    assert rows["510300.SH"] == "index:000300"
    assert rows["588200.SH"] == "index:931160"


def test_name_only_etf_joins_the_same_group_as_its_index(tmp_path, monkeypatch):
    """只有跟踪标的名、没有代码的 ETF，应通过指数目录并到同一组。"""
    _prepare(tmp_path, monkeypatch)
    from etf_engine.domain.models import IndexCatalogEntry
    from etf_engine.repositories.index_repository import IndexRepository

    IndexRepository().upsert_catalog(
        [IndexCatalogEntry(index_id="000300", index_name="沪深300指数", source_meta=_meta())]
    )
    with connect(settings.database_path) as con:
        con.execute(
            "UPDATE core.etf_master SET tracking_index_id = NULL WHERE security_id = '510310.SH'"
        )
        con.execute("UPDATE core.etf_index_map SET index_id = '' WHERE etf_id = '510310.SH'")

    compute_peer_metrics(asof=ASOF)

    with connect(settings.database_path) as con:
        rows = dict(
            con.execute("SELECT security_id, peer_group_id FROM mart.etf_peer_group").fetchall()
        )
    assert rows["510310.SH"] == "index:000300", "名称解析回代码后与同类同组"


def test_peer_compare_service_and_api(tmp_path, monkeypatch):
    _prepare(tmp_path, monkeypatch)
    compute_peer_metrics(asof=ASOF)

    rows = PeerService().compare_peers(["510300.SH", "159919.SZ"], asof_date=ASOF)

    assert [row["security_id"] for row in rows] == ["510300.SH", "159919.SZ"]
    assert rows[0]["peer_group_kind"] == "tracking_index"
    assert set(rows[0]["dimensions"]) == {
        "基础规模",
        "流动性",
        "跟踪质量",
        "成本",
        "资金与拥挤度",
    }

    response = TestClient(api_module.app).get(
        "/api/v1/research/peer-compare",
        params={"security_ids": "510300.SH,159919.SZ", "asof_date": ASOF.isoformat()},
    )
    body = response.json()
    assert response.status_code == 200
    assert body["meta"]["asof_date"] == ASOF.isoformat()
    assert body["data"][0]["dimensions"]["基础规模"]["aum_rank_pct"] == pytest.approx(1.0)


def test_overlap_endpoint_reports_shared_holdings(tmp_path, monkeypatch):
    _prepare(tmp_path, monkeypatch)

    response = TestClient(api_module.app).post(
        "/api/v1/research/overlap", json=["510300.SH", "510310.SH"]
    )
    pair = response.json()["data"]["pairs"][0]

    assert response.status_code == 200
    assert pair["common_holdings"] == ["600519.SH"]
    assert pair["holding_overlap_ratio"] == pytest.approx(1.0)
    assert pair["weighted_overlap"] == pytest.approx(4.0)


def test_tracking_quality_tool_is_registered(tmp_path, monkeypatch):
    from etf_engine.mcp.server import tool_registry

    _prepare(tmp_path, monkeypatch)
    compute_peer_metrics(asof=ASOF)

    registry = tool_registry()
    assert {"compare_peer_etfs", "get_tracking_quality", "compare_exposure_overlap"} <= set(
        registry
    )
    quality = registry["get_tracking_quality"](["510300.SH"], ASOF)
    assert quality[0]["peer_count"] == 3
