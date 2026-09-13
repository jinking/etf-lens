"""历史查询禁止 Current Fallback 集成测试。

验证在指定历史 as-of 时：
1. 找不到 PIT 映射时，tracking_index 为 NULL，tracking_index_pit 为 missing_asof，
   严禁 fallback 到 master_latest；
2. CoreMetricsRepository.tracking_index 在历史模式下找不到有效映射直接返回 None；
3. PeerService 在历史模式下找不到日快照直接返回 missing，不得自动回落到当前分组。
"""

from datetime import date, datetime
from decimal import Decimal

from etf_engine.config.settings import settings
from etf_engine.db.migrate import run_migrations
from etf_engine.domain.enums import QualityStatus
from etf_engine.domain.models import ETFMaster, ETFQuote, SourceMeta
from etf_engine.domain.research_context import ResearchContext
from etf_engine.repositories.core_metrics_repository import CoreMetricsRepository
from etf_engine.repositories.index_repository import IndexRepository
from etf_engine.repositories.master_repository import MasterRepository
from etf_engine.repositories.peer_repository import PeerRepository
from etf_engine.repositories.quote_repository import QuoteRepository
from etf_engine.repositories.trading_calendar_repository import TradingCalendarRepository
from etf_engine.services.peer_service import PeerService
from etf_engine.services.research_service import ResearchService

SECURITY_ID = "510300.SH"
T1 = date(2026, 9, 1)
T2 = date(2026, 9, 15)
FETCHED_AT = datetime(2026, 9, 15, 10, 0)


def _meta() -> SourceMeta:
    return SourceMeta(source="test", fetched_at=FETCHED_AT, quality_status=QualityStatus.PASS)


def _setup(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "database_path", tmp_path / "etf.duckdb")
    run_migrations()
    TradingCalendarRepository().upsert_many([T1, T2], source="test", upstream_source="test")

    # master 表上登记了当前的 tracking_index
    MasterRepository().upsert_many(
        [
            ETFMaster(
                security_id=SECURITY_ID,
                ticker="510300",
                exchange="SSE",
                fund_name="沪深300ETF",
                tracking_index_id="000300",
                tracking_index_name="沪深300",
                source_meta=_meta(),
            )
        ]
    )
    QuoteRepository().upsert_many(
        [
            ETFQuote(
                security_id=SECURITY_ID,
                trade_date=T1,
                close=Decimal("4.0"),
                turnover_amount=Decimal("1000000"),
                source_meta=_meta(),
            )
        ]
    )


def test_compare_forbids_master_fallback_in_historical_mode(tmp_path, monkeypatch):
    """历史查询找不到 PIT map 时，tracking_index 为 NULL，tracking_index_pit 为 missing_asof。"""
    _setup(tmp_path, monkeypatch)

    # 映射表只在 T2 生效，在 T1 查不到
    IndexRepository().upsert_map(
        [
            {
                "etf_id": SECURITY_ID,
                "index_id": "000300",
                "index_name": "沪深300",
                "valid_from": T2,
                "source": "test",
            }
        ]
    )

    row = ResearchService().compare([SECURITY_ID], ResearchContext(asof_date=T1))[0]

    assert row["tracking_index_name"] is None, "历史模式找不到 PIT map 不得 fallback master"
    assert row["tracking_index_pit"] == "missing_asof"


def test_compare_allows_master_fallback_in_latest_mode(tmp_path, monkeypatch):
    """Latest 模式（无 as-of）允许 current fallback。"""
    _setup(tmp_path, monkeypatch)

    row = ResearchService().compare([SECURITY_ID], ResearchContext(asof_date=None))[0]

    assert row["tracking_index_name"] == "沪深300"
    assert row["tracking_index_pit"] == "master_latest"


def test_core_metrics_repo_tracking_index_forbids_fallback_in_historical_mode(
    tmp_path, monkeypatch
):
    """CoreMetricsRepository.tracking_index 在历史模式下找不到有效映射直接返回 None。"""
    _setup(tmp_path, monkeypatch)

    IndexRepository().upsert_map(
        [
            {
                "etf_id": SECURITY_ID,
                "index_id": "000300",
                "index_name": "沪深300",
                "valid_from": T2,
                "source": "test",
            }
        ]
    )

    repo = CoreMetricsRepository()
    assert repo.tracking_index(SECURITY_ID, asof_date=T1) is None
    # Latest 模式允许
    latest = repo.tracking_index(SECURITY_ID, asof_date=None)
    assert latest is not None
    assert latest["index_id"] == "000300"


def test_peer_service_forbids_current_group_fallback_in_historical_mode(tmp_path, monkeypatch):
    """PeerService 在历史模式下快照不存在时返回 missing，不允许自动回落当前分组。"""
    _setup(tmp_path, monkeypatch)

    # 写入一份当前分组（无日快照）
    PeerRepository().upsert_groups(
        [
            {
                "security_id": SECURITY_ID,
                "peer_group_id": "index:000300",
                "kind": "tracking_index",
                "label": "000300",
                "peer_count": 5,
            }
        ]
    )

    service = PeerService()
    # 默认不允许 fallback
    res_strict = service.compare_peers([SECURITY_ID], asof_date=T1)
    assert res_strict[0]["peer_group_id"] is None
    assert res_strict[0]["peer_group_pit"] == "missing"

    # 显式允许 fallback 时才允许
    res_fallback = service.compare_peers([SECURITY_ID], asof_date=T1, allow_current_fallback=True)
    assert res_fallback[0]["peer_group_id"] == "index:000300"
    assert res_fallback[0]["peer_group_pit"] == "current_fallback"
