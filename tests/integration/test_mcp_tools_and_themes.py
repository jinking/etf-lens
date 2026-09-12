"""MCP 工具层与主题聚合。"""

from datetime import date, datetime
from decimal import Decimal

import pytest

from etf_engine.config.settings import settings
from etf_engine.db.migrate import run_migrations
from etf_engine.domain.enums import QualityStatus
from etf_engine.domain.models import ETFHolding, ETFMaster, ETFQuote, ETFShare, SourceMeta
from etf_engine.jobs.compute_mart import compute_mart
from etf_engine.mcp import tools
from etf_engine.mcp.server import MCPSdkNotInstalled, build_server, tool_registry
from etf_engine.repositories.holding_repository import HoldingRepository
from etf_engine.repositories.master_repository import MasterRepository
from etf_engine.repositories.quote_repository import QuoteRepository
from etf_engine.repositories.share_repository import ShareRepository
from etf_engine.repositories.tag_repository import TagRepository

FETCHED_AT = datetime(2026, 9, 12, 10, 0)
ASOF = date(2026, 9, 11)


def _meta(upstream: str = "test") -> SourceMeta:
    return SourceMeta(
        source="test",
        upstream_source=upstream,
        fetched_at=FETCHED_AT,
        quality_status=QualityStatus.PASS,
    )


@pytest.fixture
def seeded(tmp_path, monkeypatch):
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
                tracking_index_name="上证科创板芯片指数",
                source_meta=_meta(),
            )
        ]
    )
    QuoteRepository().upsert_many(
        [
            ETFQuote(
                security_id="588200.SH",
                trade_date=ASOF,
                name="科创芯片ETF",
                close=Decimal("1.089"),
                change_pct=Decimal("-1.34"),
                turnover_amount=Decimal("2360243967"),
                source_meta=_meta(),
            )
        ]
    )
    ShareRepository().upsert_many(
        [
            ETFShare(
                security_id="588200.SH",
                trade_date=ASOF,
                shares=Decimal("43000000000"),
                nav=Decimal("1.0913"),
                source_meta=_meta("sse"),
            )
        ]
    )
    HoldingRepository().upsert_many(
        [
            ETFHolding(
                etf_id="588200.SH",
                report_date=date(2026, 6, 30),
                stock_id="688981.SH",
                stock_name="中芯国际",
                weight_pct=Decimal("9.5"),
                source_meta=_meta(),
            )
        ]
    )
    TagRepository().upsert_tags(
        [
            {
                "etf_id": "588200.SH",
                "tag": "集成电路",
                "tag_type": "industry",
                "confidence": 0.72,
                "coverage": 0.95,
                "calculation_version": "tag_v1",
                "valid_from": date(2026, 6, 30),
            }
        ]
    )
    compute_mart()
    return tmp_path


def test_tool_registry_covers_the_documented_tools():
    assert set(tool_registry()) == {
        "search_etfs",
        "get_etf_profile",
        "get_etf_quote",
        "get_etf_performance",
        "get_etf_flow",
        "get_etf_holdings",
        "compare_etfs",
        "screen_etfs",
    }


def test_tools_read_from_the_service_layer(seeded):
    quote = tools.get_etf_quote("588200")
    profile = tools.get_etf_profile("588200.SH")
    holdings = tools.get_etf_holdings("588200")
    flow = tools.get_etf_flow("588200.SH")

    assert quote["security_id"] == "588200.SH"
    assert profile["master"]["tracking_index_name"] == "上证科创板芯片指数"
    assert profile["tags"][0]["tag"] == "集成电路"
    assert holdings["report_date"] == "2026-06-30"
    assert holdings["holdings"][0]["stock_id"] == "688981.SH"
    assert flow["is_estimated"] is True
    assert flow["calculation_version"] == "flow_v1"


def test_tools_reject_invalid_ids_and_report_missing_data(seeded):
    with pytest.raises(ValueError):
        tools.get_etf_quote("999999")
    with pytest.raises(LookupError):
        tools.get_etf_flow("159915.SZ")


def test_compare_and_screen_tools(seeded):
    compared = tools.compare_etfs(["588200.SH"])
    screened = tools.screen_etfs(min_aum=1_000_000_000)

    assert compared[0]["security_id"] == "588200.SH"
    assert [row["security_id"] for row in screened] == ["588200.SH"]


def test_mcp_server_reports_a_missing_sdk_clearly():
    """SDK 是可选依赖：没装时要给出可执行的提示，而不是导入即崩。"""
    try:
        import mcp  # noqa: F401
    except ImportError:
        with pytest.raises(MCPSdkNotInstalled):
            build_server()
    else:  # pragma: no cover - 安装了 SDK 的环境
        assert build_server() is not None


def test_theme_aggregation_groups_tags(seeded):
    from etf_engine.services.research_service import ResearchService

    results = ResearchService().themes()

    assert results[0]["theme"] == "集成电路"
    assert results[0]["etf_count"] == 1
    assert results[0]["calculation_version"] == "tag_v1"
