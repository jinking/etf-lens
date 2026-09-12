"""基金档案补齐：只补空，不覆盖已有事实。"""

from datetime import date, datetime
from decimal import Decimal

from etf_engine.config.settings import settings
from etf_engine.db.connection import connect
from etf_engine.db.migrate import run_migrations
from etf_engine.domain.enums import QualityStatus
from etf_engine.domain.models import ETFMaster, FundProfile, SourceMeta
from etf_engine.jobs.sync_fund_profile import sync_fund_profile
from etf_engine.repositories.master_repository import MasterRepository
from etf_engine.sources.registry import registry

FETCHED_AT = datetime(2026, 9, 12, 10, 0)


def _meta() -> SourceMeta:
    return SourceMeta(source="test", fetched_at=FETCHED_AT, quality_status=QualityStatus.PASS)


class _StubProfileSource:
    """只处理 588200（沪市，字段全空）与 159915（深市，已有管理人）。"""

    def fetch_profile(self, security_id: str) -> FundProfile:
        if security_id == "588200.SH":
            return FundProfile(
                security_id=security_id,
                fund_name="嘉实上证科创板芯片交易型开放式指数证券投资基金",
                short_name="科创芯片ETF嘉实",
                established_date=date(2022, 9, 30),
                manager_name="嘉实基金",
                custodian_name="中信证券",
                management_fee_pct=Decimal("0.50"),
                custodian_fee_pct=Decimal("0.10"),
                tracking_target="上证科创板芯片指数",
                source_meta=_meta(),
            )
        return FundProfile(
            security_id=security_id,
            fund_name="易方达创业板ETF",
            manager_name="深交所官方源的管理人",  # 不应覆盖已有值
            established_date=date(2011, 9, 20),
            source_meta=_meta(),
        )


def _prepare(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "database_path", tmp_path / "etf.duckdb")
    run_migrations()
    MasterRepository().upsert_many(
        [
            ETFMaster(
                security_id="588200.SH",
                ticker="588200",
                exchange="SSE",
                fund_name="嘉实上证科创板芯片ETF",
                source_meta=_meta(),
            ),
            ETFMaster(
                security_id="159915.SZ",
                ticker="159915",
                exchange="SZSE",
                fund_name="易方达创业板ETF",
                manager_name="易方达基金管理有限公司",
                management_fee_pct=Decimal("0.15"),
                source_meta=_meta(),
            ),
        ]
    )
    monkeypatch.setattr(type(registry), "fund_profile_source", _StubProfileSource, raising=False)


def test_profile_fills_missing_master_fields(tmp_path, monkeypatch):
    _prepare(tmp_path, monkeypatch)

    result = sync_fund_profile(limit=10, sleep_seconds=0)

    assert result["rows_written"] == 2
    with connect(settings.database_path) as con:
        row = con.execute(
            """
            SELECT established_date, manager_name, custodian_name,
                   management_fee_pct, custodian_fee_pct, tracking_index_name
            FROM core.etf_master WHERE security_id = '588200.SH'
            """
        ).fetchone()
    assert row == (date(2022, 9, 30), "嘉实基金", "中信证券", 0.5, 0.1, "上证科创板芯片指数")


def test_profile_never_overwrites_existing_facts(tmp_path, monkeypatch):
    _prepare(tmp_path, monkeypatch)

    sync_fund_profile(limit=10, sleep_seconds=0)

    with connect(settings.database_path) as con:
        row = con.execute(
            """
            SELECT manager_name, management_fee_pct FROM core.etf_master
            WHERE security_id = '159915.SZ'
            """
        ).fetchone()
    assert row == ("易方达基金管理有限公司", 0.15), "已有事实不被档案覆盖"


def test_profile_is_idempotent_and_then_skips_filled_funds(tmp_path, monkeypatch):
    _prepare(tmp_path, monkeypatch)
    sync_fund_profile(limit=10, sleep_seconds=0)

    again = sync_fund_profile(limit=10, sleep_seconds=0)

    assert again["status"] == "SKIPPED", "字段已补齐的 ETF 不再重复请求"


def test_profile_failure_is_recorded_without_stopping_the_batch(tmp_path, monkeypatch):
    _prepare(tmp_path, monkeypatch)

    class _Flaky(_StubProfileSource):
        def fetch_profile(self, security_id: str) -> FundProfile:
            if security_id == "588200.SH":
                raise ConnectionError("网络抖动")
            return super().fetch_profile(security_id)

    monkeypatch.setattr(type(registry), "fund_profile_source", _Flaky, raising=False)

    result = sync_fund_profile(limit=10, sleep_seconds=0)

    assert result["status"] == "PARTIAL"
    assert result["failures"] == 1
    assert result["rows_written"] == 1
