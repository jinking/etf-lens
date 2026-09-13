"""CoreMetrics V2 路由集成测试。

确保 ETFCoreMetricsService 统一消费生产版本的 mart（metric_v2 / flow_v2），
不再在现场自行复制公式计算 v1，消除 ResearchService 与 CoreMetricsService 的两套真相。
"""

from datetime import date, datetime
from decimal import Decimal

from etf_engine.config.settings import settings
from etf_engine.db.connection import connect
from etf_engine.db.migrate import run_migrations
from etf_engine.domain.enums import QualityStatus
from etf_engine.domain.models import ETFMaster, ETFQuote, SourceMeta
from etf_engine.domain.versions import current_flow_version, current_metric_version
from etf_engine.repositories.master_repository import MasterRepository
from etf_engine.repositories.quote_repository import QuoteRepository
from etf_engine.repositories.trading_calendar_repository import TradingCalendarRepository
from etf_engine.services.core_metrics_service import ETFCoreMetricsService

SECURITY_ID = "510300.SH"
ASOF = date(2026, 9, 11)
FETCHED_AT = datetime(2026, 9, 12, 18, 0)


def _meta() -> SourceMeta:
    return SourceMeta(source="test", fetched_at=FETCHED_AT, quality_status=QualityStatus.PASS)


def _setup_base_data(tmp_path, monkeypatch, security_id: str = SECURITY_ID) -> None:
    monkeypatch.setattr(settings, "database_path", tmp_path / "etf.duckdb")
    run_migrations()
    TradingCalendarRepository().upsert_many([ASOF], source="test", upstream_source="test")
    MasterRepository().upsert_many(
        [
            ETFMaster(
                security_id=security_id,
                ticker=security_id.split(".")[0],
                exchange="SSE",
                fund_name="测试ETF",
                source_meta=_meta(),
            )
        ]
    )
    QuoteRepository().upsert_many(
        [
            ETFQuote(
                security_id=security_id,
                trade_date=ASOF,
                close=Decimal("4.5"),
                turnover_amount=Decimal("1e9"),
                source_meta=_meta(),
            )
        ]
    )


def test_core_metrics_consumes_metric_v2_over_v1(tmp_path, monkeypatch):
    """同日 metric_v1=-50%、metric_v2=+5%，CoreMetrics 必须取 +5% 并消费 v2 指标。"""
    _setup_base_data(tmp_path, monkeypatch)

    with connect(settings.database_path) as con:
        con.executemany(
            """
            INSERT INTO mart.etf_metric_daily (
                security_id, trade_date, return_20d, return_60d,
                max_drawdown_60d, avg_turnover_amount_20d,
                calculation_version, calculated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                (SECURITY_ID, ASOF, -0.50, -0.60, -0.70, 100.0, "metric_v1", FETCHED_AT),
                (
                    SECURITY_ID,
                    ASOF,
                    0.05,
                    0.15,
                    -0.05,
                    200.0,
                    current_metric_version(),
                    FETCHED_AT,
                ),
            ],
        )

    metrics = ETFCoreMetricsService().get_core_metrics(SECURITY_ID, ASOF)

    assert metrics.market_return_20d == 0.05, "market_return_20d 必须取 metric_v2 (+5%)"
    assert metrics.market_return_60d == 0.15, "market_return_60d 必须取 metric_v2 (+15%)"
    assert metrics.max_drawdown_60d == -0.05, "max_drawdown_60d 必须取 metric_v2 (-5%)"
    assert metrics.avg_turnover_amount_20d == 200.0, "avg_turnover_amount_20d 必须取 metric_v2"


def test_core_metrics_consumes_flow_v2_over_v1(tmp_path, monkeypatch):
    """同日 flow_v1=-100亿、flow_v2=+2亿，CoreMetrics 必须取 +2亿。"""
    _setup_base_data(tmp_path, monkeypatch)

    with connect(settings.database_path) as con:
        con.executemany(
            """
            INSERT INTO mart.etf_flow_daily (
                security_id, trade_date, share_change_20d, share_change_pct_20d,
                estimated_net_subscription_20d, is_estimated,
                calculation_version, calculated_at
            ) VALUES (?, ?, ?, ?, ?, TRUE, ?, ?)
            """,
            [
                (
                    SECURITY_ID,
                    ASOF,
                    -100_000_000.0,
                    -0.10,
                    -10_000_000_000.0,
                    "flow_v1",
                    FETCHED_AT,
                ),
                (
                    SECURITY_ID,
                    ASOF,
                    2_000_000.0,
                    0.02,
                    200_000_000.0,
                    current_flow_version(),
                    FETCHED_AT,
                ),
            ],
        )

    metrics = ETFCoreMetricsService().get_core_metrics(SECURITY_ID, ASOF)

    assert metrics.share_change_20d == 2_000_000.0
    assert metrics.share_change_pct_20d == 0.02
    assert metrics.estimated_net_subscription_20d == 200_000_000.0
    assert metrics.estimated_net_subscription_calculation_version == current_flow_version()


def test_515880_corporate_action_does_not_report_corporate_action_in_window_when_v2_valid(
    tmp_path, monkeypatch
):
    """515880 跨折算窗口：metric_v2 有值时不得报 corporate_action_in_window。"""
    sec_id = "515880.SH"
    monkeypatch.setattr(settings, "database_path", tmp_path / "etf.duckdb")
    run_migrations()
    TradingCalendarRepository().upsert_many([ASOF], source="test", upstream_source="test")
    MasterRepository().upsert_many(
        [
            ETFMaster(
                security_id=sec_id,
                ticker="515880",
                exchange="SSE",
                fund_name="通信ETF",
                source_meta=_meta(),
            )
        ]
    )
    # 模拟未复权序列有断崖式价格跳变（引发 has_unadjusted_jump）
    quotes = [
        ETFQuote(
            security_id=sec_id,
            trade_date=date(2026, 8, 1),
            close=Decimal("2.0"),
            source_meta=_meta(),
        ),
        ETFQuote(
            security_id=sec_id,
            trade_date=ASOF,
            close=Decimal("1.0"),
            source_meta=_meta(),
        ),
    ]
    QuoteRepository().upsert_many(quotes)

    with connect(settings.database_path) as con:
        con.execute(
            """
            INSERT INTO mart.etf_metric_daily (
                security_id, trade_date, return_20d, return_60d,
                max_drawdown_60d, avg_turnover_amount_20d,
                calculation_version, calculated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [sec_id, ASOF, 0.05, 0.10, -0.04, 500000.0, current_metric_version(), FETCHED_AT],
        )

    metrics = ETFCoreMetricsService().get_core_metrics(sec_id, ASOF)

    assert metrics.market_return_20d == 0.05
    assert "corporate_action_in_window" not in metrics.quality.reasons.values(), (
        f"v2 有有效值时不得报 corporate_action_in_window，当前 reasons: {metrics.quality.reasons}"
    )
