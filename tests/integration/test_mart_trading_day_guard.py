"""mart 计算的交易日守卫。

历史事故：深交所份额快照曾用运行日（周六）当交易日写入，compute_mart 随即
算出一条"周六的申赎记录"，并一直留在 mart 里污染后续查询
（看盘台的新鲜度面板正是先看到这条 2026-09-12 的申赎日期才发现的）。
"""

from datetime import date, datetime, timedelta

from etf_engine.config.settings import settings
from etf_engine.db.connection import connect
from etf_engine.db.migrate import run_migrations
from etf_engine.domain.enums import QualityStatus
from etf_engine.domain.models import ETFQuote, ETFShare, SourceMeta
from etf_engine.jobs.compute_mart import compute_mart
from etf_engine.repositories.quote_repository import QuoteRepository
from etf_engine.repositories.share_repository import ShareRepository
from etf_engine.repositories.trading_calendar_repository import TradingCalendarRepository

FETCHED_AT = datetime(2026, 9, 12, 18, 0)
TRADING_DAY = date(2026, 9, 10)  # 周四
NON_TRADING_DAY = date(2026, 9, 12)  # 周六


def _meta() -> SourceMeta:
    return SourceMeta(
        source="test", upstream_source="test", fetched_at=FETCHED_AT,
        quality_status=QualityStatus.PASS,
    )


def _prepare(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "database_path", tmp_path / "etf.duckdb")
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


def test_compute_mart_refuses_non_trading_dates(tmp_path, monkeypatch):
    _prepare(tmp_path, monkeypatch)
    QuoteRepository().upsert_many(
        [
            ETFQuote(
                security_id="588200.SH", trade_date=day, close=1.0,
                turnover_amount=1e8, source_meta=_meta(),
            )
            for day in (TRADING_DAY, NON_TRADING_DAY)
        ]
    )
    ShareRepository().upsert_many(
        [
            ETFShare(
                security_id="588200.SH", trade_date=day, shares=1e9, nav=1.0,
                source_meta=_meta(),
            )
            for day in (TRADING_DAY, NON_TRADING_DAY)
        ]
    )

    result = compute_mart()

    # 周六的快照被拦下，且必须留痕，不是静默丢弃
    assert result["rows_rejected"] >= 1
    with connect(settings.database_path) as con:
        metric_dates = [
            row[0]
            for row in con.execute(
                "SELECT DISTINCT trade_date FROM mart.etf_metric_daily"
            ).fetchall()
        ]
        flow_dates = [
            row[0]
            for row in con.execute(
                "SELECT DISTINCT trade_date FROM mart.etf_flow_daily"
            ).fetchall()
        ]
        issue_rules = {
            row[0]
            for row in con.execute(
                "SELECT DISTINCT rule_name FROM ops.quality_issue"
            ).fetchall()
        }

    assert NON_TRADING_DAY not in metric_dates
    assert NON_TRADING_DAY not in flow_dates
    assert TRADING_DAY in metric_dates
    assert "metric_trade_date_not_trading_day" in issue_rules
    assert "flow_trade_date_not_trading_day" in issue_rules
