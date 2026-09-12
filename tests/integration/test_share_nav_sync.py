"""份额同步的端到端行为（不访问外网）。"""

from datetime import date, datetime, timedelta
from decimal import Decimal

import pandas as pd
import pytest
from typer.testing import CliRunner

from etf_engine.cli.app import app as cli_app
from etf_engine.config.settings import settings
from etf_engine.db.connection import connect
from etf_engine.db.migrate import run_migrations
from etf_engine.domain.enums import QualityStatus
from etf_engine.domain.models import ETFNav, SourceMeta
from etf_engine.jobs.sync_shares import sync_shares
from etf_engine.repositories.nav_repository import NavRepository
from etf_engine.repositories.trading_calendar_repository import TradingCalendarRepository
from etf_engine.sources.sse import shares as sse_shares
from etf_engine.sources.szse import shares as szse_shares

SSE_ROWS = [
    {"SEC_CODE": "510010", "SEC_NAME": "治理ETF", "STAT_DATE": "2026-09-11", "TOT_VOL": "13052.44"},
    {"SEC_CODE": "510300", "SEC_NAME": "沪深300ETF", "STAT_DATE": "2026-09-11", "TOT_VOL": "2000"},
]

SZSE_FRAME = pd.DataFrame(
    [
        {"基金代码": "159915", "基金简称": "创业板ETF", "当前规模(份)": "1,000,000", "净值": "3.3"},
        # 负份额：必须被 validator 拦下并写入 ops.quality_issue
        {"基金代码": "159999", "基金简称": "坏数据ETF", "当前规模(份)": "-5", "净值": "1"},
        # 份额 0：上游"该日无数据"的占位值，同样不能当事实（会变成假的巨额赎回）
        {"基金代码": "159998", "基金简称": "零份额ETF", "当前规模(份)": "0", "净值": "1"},
    ]
)


_FROZEN_SATURDAY = type(
    "FrozenDatetime",
    (),
    {"now": staticmethod(lambda tz=None: datetime(2026, 9, 12, 17, 30))},
)


def _seed_calendar() -> None:
    days = [
        date(2026, 1, 1) + timedelta(days=offset)
        for offset in range(365)
        if (date(2026, 1, 1) + timedelta(days=offset)).weekday() < 5
    ]
    TradingCalendarRepository().upsert_many(days, source="test", upstream_source="test")


def _setup(tmp_path, monkeypatch, rows_by_date=None) -> None:
    monkeypatch.setattr(settings, "database_path", tmp_path / "etf.duckdb")
    monkeypatch.setattr(settings, "raw_path", tmp_path / "raw")
    run_migrations()
    _seed_calendar()
    if rows_by_date is None:
        monkeypatch.setattr(
            sse_shares, "_fetch_sse_scale_rows", lambda stat_date, **kwargs: SSE_ROWS
        )
    else:
        # 用真实的上游语义打桩：接口按 STAT_DATE 返回该日数据，缺失日期返回空。
        monkeypatch.setattr(
            sse_shares,
            "_fetch_sse_scale_rows",
            lambda stat_date, **kwargs: rows_by_date.get(stat_date, []),
        )
    monkeypatch.setattr(szse_shares, "fetch_szse_fund_frame", lambda **kwargs: SZSE_FRAME)


def _row(stat_date: str, volume: str) -> dict:
    return {
        "SEC_CODE": "510010",
        "SEC_NAME": "治理ETF",
        "STAT_DATE": stat_date,
        "TOT_VOL": volume,
    }


def test_share_sync_uses_trading_calendar_and_never_stamps_a_weekend(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    monkeypatch.setattr("etf_engine.jobs.sync_shares.datetime", _FROZEN_SATURDAY)

    result = sync_shares()

    assert result["asof_date"] == "2026-09-11", "周六运行必须回退到周五"
    with connect(settings.database_path) as con:
        stored_dates = {
            row[0]
            for row in con.execute(
                "SELECT DISTINCT trade_date FROM core.etf_share_daily"
            ).fetchall()
        }
    assert stored_dates == {date(2026, 9, 11)}


def test_share_sync_marks_calendar_derived_snapshot_dates(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)
    monkeypatch.setattr("etf_engine.jobs.sync_shares.datetime", _FROZEN_SATURDAY)

    sync_shares()

    with connect(settings.database_path) as con:
        issues = con.execute(
            "SELECT rule_name FROM ops.quality_issue "
            "WHERE rule_name = 'share_snapshot_date_derived'"
        ).fetchall()
    assert len(issues) == 1, "深交所快照日期是推导出来的，必须留痕"


def test_share_sync_rejects_bad_rows_and_records_quality_issues(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)

    sync_shares(trade_date=date(2026, 9, 11))

    with connect(settings.database_path) as con:
        rows = con.execute(
            "SELECT security_id, shares FROM core.etf_share_daily ORDER BY security_id"
        ).fetchall()
        issues = con.execute(
            "SELECT severity, rule_name, security_id FROM ops.quality_issue "
            "WHERE severity = 'ERROR'"
        ).fetchall()

    assert [row[0] for row in rows] == ["159915.SZ", "510010.SH", "510300.SH"]
    assert ("ERROR", "shares_positive", "159999.SZ") in issues
    assert ("ERROR", "shares_positive", "159998.SZ") in issues


def test_share_sync_enriches_missing_nav_from_the_nav_source(tmp_path, monkeypatch):
    """上交所规模接口没有净值，必须用独立净值来源补齐规模估算，并标注来源。"""
    _setup(tmp_path, monkeypatch)
    NavRepository().upsert_many(
        [
            ETFNav(
                security_id="510010.SH",
                nav_date=date(2026, 9, 11),
                unit_nav=Decimal("2.5"),
                source_meta=SourceMeta(
                    source="akshare",
                    upstream_source="eastmoney",
                    fetched_at=datetime(2026, 9, 12, 10, 0),
                    quality_status=QualityStatus.PASS,
                ),
            )
        ]
    )

    sync_shares(trade_date=date(2026, 9, 11))

    with connect(settings.database_path) as con:
        row = con.execute(
            """
            SELECT shares, nav, nav_source, estimated_aum, is_estimated_aum
            FROM core.etf_share_daily WHERE security_id = '510010.SH'
            """
        ).fetchone()

    assert row[1] == 2.5
    assert row[2] == "akshare/eastmoney"
    assert row[3] == pytest.approx(326_311_000.0)
    assert row[4] is True


def test_share_sync_scales_sse_volume_to_shares(tmp_path, monkeypatch):
    _setup(tmp_path, monkeypatch)

    sync_shares(trade_date=date(2026, 9, 11))

    with connect(settings.database_path) as con:
        shares = con.execute(
            "SELECT shares FROM core.etf_share_daily WHERE security_id = '510300.SH'"
        ).fetchone()[0]
    assert shares == Decimal("2000") * 10000


def test_cli_exposes_calendar_and_nav_commands():
    result = CliRunner().invoke(cli_app, ["--help"])

    assert result.exit_code == 0
    assert "sync-calendar" in result.stdout
    assert "sync-nav" in result.stdout


def test_share_backfill_only_applies_to_sources_with_their_own_dates(tmp_path, monkeypatch):
    """上交所可按交易日回补；深交所是快照，禁止复制成多条历史。"""
    rows_by_date = {
        "20260909": [_row("2026-09-09", "100")],
        "20260910": [],  # 上游缺当日披露，必须留缺口而不是插值
        "20260911": [_row("2026-09-11", "150")],
    }
    _setup(tmp_path, monkeypatch, rows_by_date=rows_by_date)

    result = sync_shares(trade_date=date(2026, 9, 11), backfill_days=3)

    with connect(settings.database_path) as con:
        sse_dates = [
            row[0]
            for row in con.execute(
                "SELECT trade_date FROM core.etf_share_daily "
                "WHERE security_id = '510010.SH' ORDER BY trade_date"
            ).fetchall()
        ]
        szse_dates = [
            row[0]
            for row in con.execute(
                "SELECT trade_date FROM core.etf_share_daily "
                "WHERE security_id = '159915.SZ' ORDER BY trade_date"
            ).fetchall()
        ]
        gap_issues = con.execute(
            "SELECT count(*) FROM ops.quality_issue WHERE rule_name = 'share_history_missing_date'"
        ).fetchone()[0]

    assert sse_dates == [date(2026, 9, 9), date(2026, 9, 11)]
    assert szse_dates == [date(2026, 9, 11)], "快照来源只能写一个日期"
    assert gap_issues == 1
    assert result["sources"][0]["backfill_days"] == 3
