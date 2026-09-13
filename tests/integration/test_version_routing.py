"""版本路由：同一天同时存在 v1/v2 时，研究查询必须稳定取到生产版本。

复现的是 V2.1 P0-1：``ROW_NUMBER() ... ORDER BY trade_date DESC`` 在
``security_id + trade_date`` 相同、``calculation_version`` 不同的情况下，
取哪一行由数据库决定——研究结论会随执行计划漂移。
"""

from datetime import date, datetime
from decimal import Decimal

from etf_engine.config.settings import settings
from etf_engine.db.connection import connect
from etf_engine.db.migrate import run_migrations
from etf_engine.domain.enums import QualityStatus
from etf_engine.domain.models import ETFMaster, ETFQuote, SourceMeta
from etf_engine.domain.research_context import ResearchContext
from etf_engine.domain.versions import current_flow_version, current_metric_version
from etf_engine.repositories.master_repository import MasterRepository
from etf_engine.repositories.quote_repository import QuoteRepository
from etf_engine.repositories.trading_calendar_repository import TradingCalendarRepository
from etf_engine.services.research_service import ResearchService

SECURITY_ID = "510300.SH"
ASOF = date(2026, 9, 11)
FETCHED_AT = datetime(2026, 9, 12, 18, 0)


def _meta() -> SourceMeta:
    return SourceMeta(source="test", fetched_at=FETCHED_AT, quality_status=QualityStatus.PASS)


def _prepare(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "database_path", tmp_path / "etf.duckdb")
    run_migrations()
    TradingCalendarRepository().upsert_many([ASOF], source="test", upstream_source="test")
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
                trade_date=ASOF,
                close=Decimal("4.5"),
                turnover_amount=Decimal("1e9"),
                source_meta=_meta(),
            )
        ]
    )
    # 同一天写入 v1 与 v2，值故意不同：研究必须取到生产版本那一行。
    with connect(settings.database_path) as con:
        con.executemany(
            """
            INSERT INTO mart.etf_metric_daily
                (security_id, trade_date, return_20d, calculation_version, calculated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            [
                (SECURITY_ID, ASOF, 0.01, "metric_v1", FETCHED_AT),
                (SECURITY_ID, ASOF, 0.99, current_metric_version(), FETCHED_AT),
            ],
        )
        con.executemany(
            """
            INSERT INTO mart.etf_flow_daily
                (security_id, trade_date, share_change_20d, is_estimated,
                 calculation_version, calculated_at)
            VALUES (?, ?, ?, TRUE, ?, ?)
            """,
            [
                (SECURITY_ID, ASOF, 1.0, "flow_v1", FETCHED_AT),
                (SECURITY_ID, ASOF, 999.0, current_flow_version(), FETCHED_AT),
            ],
        )


def test_compare_uses_the_production_version(tmp_path, monkeypatch):
    _prepare(tmp_path, monkeypatch)

    row = ResearchService().compare([SECURITY_ID], ResearchContext(asof_date=ASOF))[0]

    assert row["return_20d"] == 0.99, "指标必须取生产版本（v2），不是 v1"
    assert row["share_change_20d"] == 999.0, "资金流同理"
    assert row["metric_calculation_version"] == current_metric_version()
    assert row["flow_calculation_version"] == current_flow_version()


def test_screen_uses_the_production_version(tmp_path, monkeypatch):
    _prepare(tmp_path, monkeypatch)

    rows = ResearchService().screen(min_return_20d=0.5, context=ResearchContext(asof_date=ASOF))

    assert [row["security_id"] for row in rows] == [SECURITY_ID]
    assert rows[0]["return_20d"] == 0.99


def test_repeated_compare_is_byte_for_byte_stable(tmp_path, monkeypatch):
    """升级方案 §21 Case C：同日 v1/v2 并存时，重复 100 次结果必须完全一致。

    旧实现靠 ``ROW_NUMBER`` 的 tie-break 决定取哪一行，同一天重复查询可能漂移；
    这里把"稳定"变成可执行的断言，而不是靠观察。
    """
    _prepare(tmp_path, monkeypatch)
    service = ResearchService()

    first = service.compare([SECURITY_ID], ResearchContext(asof_date=ASOF))[0]
    for _ in range(100):
        assert service.compare([SECURITY_ID], ResearchContext(asof_date=ASOF))[0] == first

    assert first["metric_calculation_version"] == current_metric_version()
    assert first["flow_calculation_version"] == current_flow_version()


def test_resolver_rejects_unknown_blocks():
    import pytest

    from etf_engine.domain.versions import version_for

    with pytest.raises(KeyError):
        version_for("not_a_block")


def test_production_version_registry_is_consistent():
    """按表名的默认口径与按层的 Resolver 必须指的是同一版，否则又是两套真相。"""
    from etf_engine.domain.versions import CURRENT_VERSION_BY_DATASET

    assert CURRENT_VERSION_BY_DATASET["mart.etf_metric_daily"] == current_metric_version()
    assert CURRENT_VERSION_BY_DATASET["mart.etf_flow_daily"] == current_flow_version()
    assert current_metric_version() != "metric_v1", "默认研究口径必须是 v2（升级方案 §2.6）"
    assert current_flow_version() != "flow_v1"
