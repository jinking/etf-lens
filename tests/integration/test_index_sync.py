"""指数链路端到端（打桩上游，不访问网络）。"""

from datetime import date, datetime, timedelta

import pandas as pd

from etf_engine.config.settings import settings
from etf_engine.db.connection import connect
from etf_engine.db.migrate import run_migrations
from etf_engine.domain.enums import QualityStatus
from etf_engine.domain.models import SourceMeta
from etf_engine.jobs.sync_index import sync_index_catalog, sync_index_details, sync_index_map
from etf_engine.repositories.index_repository import IndexRepository
from etf_engine.repositories.master_repository import MasterRepository
from etf_engine.repositories.trading_calendar_repository import TradingCalendarRepository
from etf_engine.sources.registry import registry

FETCHED_AT = datetime(2026, 9, 12, 10, 0)

CATALOG_FRAME = pd.DataFrame(
    [
        {"指数代码": "000300", "指数全称": "沪深300指数", "指数简称": "沪深300"},
        {"指数代码": "931160", "指数全称": "中证全指通信设备指数", "指数简称": "通信设备"},
    ]
)
SINA_FRAME = pd.DataFrame([{"代码": "sh000300", "名称": "沪深300"}])
CONSTITUENT_FRAME = pd.DataFrame(
    [
        {"日期": "2026-08-31", "成分券代码": "600519", "成分券名称": "贵州茅台", "权重": 4.2},
        {"日期": "2026-08-31", "成分券代码": "300750", "成分券名称": "宁德时代", "权重": 3.1},
    ]
)
QUOTE_FRAME = pd.DataFrame(
    [
        {"date": date(2026, 9, 10), "open": 4500.0, "high": 4520.0, "low": 4480.0, "close": 4510.0},
        {"date": date(2026, 9, 11), "open": 4510.0, "high": 4530.0, "low": 4500.0, "close": 4520.0},
    ]
)

BENCHMARKS = {
    "510300.SH": "沪深300指数收益率",
    "515880.SH": "中证全指通信设备指数收益率",
    "588200.SH": "某个没有对应指数的基准收益率",
}


class _CatalogSource:
    def fetch_catalog(self):
        from etf_engine.domain.models import IndexCatalogEntry
        from etf_engine.sources.akshare.index_data import (
            parse_csindex_catalog,
            parse_sina_symbols,
        )

        symbols = parse_sina_symbols(SINA_FRAME)
        entries = [
            IndexCatalogEntry(
                index_id=code,
                index_name=full_name,
                market_symbol=symbols.get(code),
                source_meta=SourceMeta(
                    source="csindex", fetched_at=FETCHED_AT, quality_status=QualityStatus.PASS
                ),
            )
            for code, full_name, _ in parse_csindex_catalog(CATALOG_FRAME)
        ]
        return entries, []


class _ConstituentSource:
    def fetch_constituents_with_issues(self, index_id):
        from etf_engine.sources.akshare.index_data import parse_constituent_frame

        return parse_constituent_frame(CONSTITUENT_FRAME, index_id=index_id, fetched_at=FETCHED_AT)


class _QuoteSource:
    def fetch_quotes(self, index_id, market_symbol, start_date, end_date):
        from etf_engine.sources.akshare.index_data import parse_index_quote_frame

        quotes = parse_index_quote_frame(
            QUOTE_FRAME,
            index_id=index_id,
            fetched_at=FETCHED_AT,
            start_date=start_date,
            end_date=end_date,
        )
        return quotes, []


def _prepare(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "database_path", tmp_path / "etf.duckdb")
    monkeypatch.setattr(settings, "raw_path", tmp_path / "raw")
    run_migrations()
    base = date(2026, 1, 1)
    TradingCalendarRepository().upsert_many(
        [
            base + timedelta(days=offset)
            for offset in range(365)
            if (base + timedelta(days=offset)).weekday() < 5
        ],
        source="test",
        upstream_source="test",
    )
    from etf_engine.domain.models import ETFMaster

    MasterRepository().upsert_many(
        [
            ETFMaster(
                security_id=security_id,
                ticker=security_id.split(".")[0],
                exchange="SSE",
                fund_name=security_id,
                source_meta=SourceMeta(
                    source="test", fetched_at=FETCHED_AT, quality_status=QualityStatus.PASS
                ),
            )
            for security_id in BENCHMARKS
        ]
    )
    monkeypatch.setattr(type(registry), "index_catalog_source", _CatalogSource, raising=False)
    monkeypatch.setattr(
        type(registry), "index_constituent_source", _ConstituentSource, raising=False
    )
    monkeypatch.setattr(type(registry), "index_quote_source", _QuoteSource, raising=False)


def test_index_catalog_then_map_then_details(tmp_path, monkeypatch):
    _prepare(tmp_path, monkeypatch)

    catalog_result = sync_index_catalog()
    map_result = sync_index_map(benchmark_lookup=lambda sid: BENCHMARKS[sid], sleep_seconds=0)

    assert catalog_result["rows_written"] == 2
    assert catalog_result["with_market_symbol"] == 1
    assert map_result["rows_written"] == 2
    assert map_result["unmatched"] == 1, "匹配不到基准的 ETF 不写映射"

    details = sync_index_details()

    assert details["index_count"] == 2
    assert details["constituents_written"] == 4
    assert details["quotes_written"] == 2, "只有沪深300有行情符号"

    with connect(settings.database_path) as con:
        mapping = con.execute(
            "SELECT etf_id, index_id FROM core.etf_index_map ORDER BY etf_id"
        ).fetchall()
        master = con.execute(
            "SELECT tracking_index_id FROM core.etf_master WHERE security_id = '510300.SH'"
        ).fetchone()
        issues = {
            row[0]
            for row in con.execute(
                "SELECT rule_name FROM ops.quality_issue WHERE dataset = 'index_details'"
            ).fetchall()
        }
    assert mapping == [("510300.SH", "000300"), ("515880.SH", "931160")]
    assert master == ("000300",), "master 的跟踪指数同步回填"
    assert "index_quote_source_missing" in issues, "没有行情符号的指数必须留痕"


def test_index_map_requires_catalog_first(tmp_path, monkeypatch):
    _prepare(tmp_path, monkeypatch)

    result = sync_index_map(benchmark_lookup=lambda sid: BENCHMARKS[sid], sleep_seconds=0)

    assert result["status"] == "SKIPPED"


def test_index_map_is_idempotent_and_skips_already_mapped(tmp_path, monkeypatch):
    _prepare(tmp_path, monkeypatch)
    sync_index_catalog()
    sync_index_map(benchmark_lookup=lambda sid: BENCHMARKS[sid], sleep_seconds=0)

    again = sync_index_map(benchmark_lookup=lambda sid: BENCHMARKS[sid], sleep_seconds=0)

    assert again["rows_written"] == 0, "已映射的 ETF 不再重复处理"
    with connect(settings.database_path) as con:
        assert con.execute("SELECT count(*) FROM core.etf_index_map").fetchone()[0] == 2


def test_index_quotes_are_not_refetched_within_the_window(tmp_path, monkeypatch):
    _prepare(tmp_path, monkeypatch)
    sync_index_catalog()
    sync_index_map(benchmark_lookup=lambda sid: BENCHMARKS[sid], sleep_seconds=0)
    sync_index_details()

    class _ExplodingQuoteSource:
        def fetch_quotes(self, *args, **kwargs):
            raise AssertionError("窗口内已有行情时不应再次请求")

    monkeypatch.setattr(type(registry), "index_quote_source", _ExplodingQuoteSource, raising=False)

    details = sync_index_details()

    assert details["quotes_written"] == 0


def test_tracking_error_becomes_available_after_index_sync(tmp_path, monkeypatch):
    """指数行情 + 净值齐备后，60 日跟踪误差不再是缺失原因。"""
    _prepare(tmp_path, monkeypatch)
    sync_index_catalog()
    sync_index_map(benchmark_lookup=lambda sid: BENCHMARKS[sid], sleep_seconds=0)
    sync_index_details()

    repo = IndexRepository()
    assert repo.index_ids_with_quotes(date(2026, 1, 1), date(2026, 12, 31)) == {"000300"}
