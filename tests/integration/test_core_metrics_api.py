from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from typer.testing import CliRunner

from etf_engine.api import app as api_module
from etf_engine.cli.app import app as cli_app
from etf_engine.config.settings import settings
from etf_engine.db.connection import connect
from etf_engine.db.migrate import run_migrations
from etf_engine.domain.enums import QualityStatus
from etf_engine.domain.models import ETFQuote, ETFShare, SourceMeta
from etf_engine.repositories.index_repository import IndexRepository
from etf_engine.repositories.quote_repository import QuoteRepository
from etf_engine.repositories.share_repository import ShareRepository
from etf_engine.services.core_metrics_service import ETFCoreMetricsService


def _meta() -> SourceMeta:
    return SourceMeta(
        source="test",
        fetched_at=datetime(2026, 8, 13, 15, 0),
        quality_status=QualityStatus.PASS,
    )


def test_core_metrics_endpoint_aggregates_facts_and_derived_metrics(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "database_path", tmp_path / "etf.duckdb")
    run_migrations()
    asof = date(2026, 8, 13)
    dates = [asof - timedelta(days=60 - offset) for offset in range(61)]
    QuoteRepository().upsert_many(
        [
            ETFQuote(
                security_id="588200.SH",
                trade_date=trade_date,
                name="测试ETF",
                close=Decimal(str(100 + offset)),
                turnover_amount=Decimal(str(1_000_000 + offset)),
                iopv=Decimal(str(99 + offset)),
                bid1=Decimal(str(99.9 + offset)),
                ask1=Decimal(str(100.1 + offset)),
                source_meta=_meta(),
            )
            for offset, trade_date in enumerate(dates)
        ]
    )
    ShareRepository().upsert_many(
        [
            ETFShare(
                security_id="588200.SH",
                trade_date=trade_date,
                shares=Decimal(str(1_000 + offset)),
                nav=Decimal(str(1 + offset / 1000)),
                source_meta=_meta(),
            )
            for offset, trade_date in enumerate(dates)
        ]
    )

    with connect(settings.database_path) as con:
        con.execute(
            """
            INSERT INTO core.etf_master (
                security_id, ticker, exchange, fund_name, tracking_index_id,
                tracking_index_name, reported_aum, reported_aum_date
            ) VALUES ('588200.SH', '588200', 'SSE', '测试ETF', '000001.SH', '测试指数', 1234567, ?)
            """,
            [asof],
        )
        con.execute(
            """
            INSERT INTO core.etf_holding_disclosure
            VALUES ('588200.SH', ?, ?, '000001.SZ', '测试股票', 10, 100, 1000, 'test', ?)
            """,
            [asof, asof, datetime(2026, 8, 13, 15, 0)],
        )
        con.execute(
            """
            INSERT INTO core.index_quote_daily
            SELECT '000001.SH', trade_date, NULL, NULL, NULL, close * 0.01, 'CNY', 'test', ?, 'PASS'
            FROM core.etf_quote_daily
            WHERE security_id = '588200.SH'
            """,
            [datetime(2026, 8, 13, 15, 0)],
        )
        con.execute(
            """
            INSERT INTO core.etf_nav_daily
            SELECT security_id, trade_date, close * 0.01, NULL, 'test', ?, 'PASS'
            FROM core.etf_quote_daily
            WHERE security_id = '588200.SH'
            """,
            [datetime(2026, 8, 13, 15, 0)],
        )

    from etf_engine.jobs.compute_adjusted_series import compute_adjusted_series
    from etf_engine.jobs.compute_mart import compute_mart
    from etf_engine.repositories.trading_calendar_repository import TradingCalendarRepository

    TradingCalendarRepository().upsert_many(dates, source="test", upstream_source="test")
    compute_adjusted_series(["588200.SH"])
    compute_mart(["588200.SH"])

    response = TestClient(api_module.app).get("/api/v1/etfs/588200.SH/core-metrics")
    body = response.json()

    assert response.status_code == 200
    assert body["data"]["tracking_index"]["name"] == "测试指数"
    assert body["data"]["top10_concentration"] == 0.1
    assert body["data"]["premium_discount_pct"] == 1 / 159
    assert body["data"]["avg_turnover_amount_20d"] == 1_000_050.5
    assert body["data"]["bid_ask_spread_pct"] is not None
    assert body["data"]["reported_aum"] == 1_234_567
    assert body["data"]["estimated_aum"] == 1_123.6
    assert body["data"]["estimated_aum_is_estimated"] is True
    assert body["data"]["share_change_20d"] == 20
    assert body["data"]["estimated_net_subscription_20d"] is not None
    assert body["data"]["estimated_net_subscription_is_estimated"] is True
    assert body["data"]["estimated_net_subscription_calculation_version"] == "flow_v2"
    assert body["data"]["market_return_20d"] == pytest.approx(20 / 140)
    assert body["data"]["market_return_60d"] == pytest.approx(0.6)
    assert body["data"]["max_drawdown_60d"] == 0
    assert body["data"]["tracking_error_60d"] == 0
    assert body["meta"]["quality"] == "PASS"


def test_core_metrics_returns_null_with_reasons_when_facts_are_unavailable(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "database_path", tmp_path / "etf.duckdb")
    run_migrations()
    QuoteRepository().upsert_many(
        [
            ETFQuote(
                security_id="588200.SH",
                trade_date=date(2026, 8, 13),
                close=Decimal("1"),
                source_meta=_meta(),
            )
        ]
    )

    response = TestClient(api_module.app).get("/api/v1/etfs/588200.SH/core-metrics")
    body = response.json()

    assert response.status_code == 200
    assert body["data"]["share_change_20d"] is None
    assert body["data"]["tracking_error_60d"] is None
    assert body["data"]["quality"]["reasons"]["share_change_20d"] == "share_data_unavailable"
    assert body["data"]["quality"]["reasons"]["tracking_error_60d"] == "tracking_index_unavailable"


def test_metrics_cli_returns_the_same_core_metrics_payload(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "database_path", tmp_path / "etf.duckdb")
    run_migrations()
    QuoteRepository().upsert_many(
        [
            ETFQuote(
                security_id="588200.SH",
                trade_date=date(2026, 8, 13),
                close=Decimal("1"),
                source_meta=_meta(),
            )
        ]
    )

    result = CliRunner().invoke(cli_app, ["metrics", "588200.SH"])

    assert result.exit_code == 0
    assert '"security_id": "588200.SH"' in result.stdout


def test_tracking_index_prefers_the_mapping_even_when_recorded_later(tmp_path, monkeypatch):
    """映射的 valid_from 只是观测日；as-of 早于观测日时也应命中映射而非 master 副本。"""
    monkeypatch.setattr(settings, "database_path", tmp_path / "etf.duckdb")
    run_migrations()
    QuoteRepository().upsert_many(
        [
            ETFQuote(
                security_id="510300.SH",
                trade_date=date(2026, 9, 11),
                close=Decimal("1"),
                source_meta=_meta(),
            )
        ]
    )
    IndexRepository().upsert_map(
        [
            {
                "etf_id": "510300.SH",
                "index_id": "000300",
                "index_name": "沪深300指数",
                "valid_from": date(2026, 9, 12),  # 观测日晚于 as-of
                "source": "fund_benchmark",
            }
        ]
    )

    metrics = ETFCoreMetricsService().get_core_metrics("510300.SH", date(2026, 9, 11))

    assert metrics.tracking_index.id == "000300"
    assert metrics.tracking_index.source == "fund_benchmark"
