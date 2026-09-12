"""三层状态历史回放（热力图的数据来源）。

回放不是"重新发明一遍规则"，而是拿同一套 ``pulse_v2`` 规则在历史每一天上
重算。因此必须验证：

* 每一天都只用到**当天为止**的事实（不能偷看未来）；
* 缺数据的日子如实写 UNKNOWN，不硬凑结论；
* 同一份事实重跑一次，结果一致（幂等）。
"""

from datetime import date, datetime, timedelta
from decimal import Decimal

from etf_engine.config.settings import settings
from etf_engine.db.connection import connect
from etf_engine.db.migrate import run_migrations
from etf_engine.domain.enums import Exchange, QualityStatus
from etf_engine.domain.models import MarginBalance, MarketTurnover, SourceMeta
from etf_engine.jobs.compute_pulse import backfill_pulse_history
from etf_engine.repositories.market_repository import MarketRepository
from etf_engine.repositories.trading_calendar_repository import TradingCalendarRepository

FETCHED_AT = datetime(2026, 9, 12, 18, 0)


def _meta(source: str) -> SourceMeta:
    return SourceMeta(
        source=source, upstream_source=source, fetched_at=FETCHED_AT,
        quality_status=QualityStatus.PASS,
    )


def _trading_days(count: int) -> list[date]:
    base = date(2026, 1, 5)  # 周一
    days: list[date] = []
    offset = 0
    while len(days) < count:
        candidate = base + timedelta(days=offset)
        if candidate.weekday() < 5:
            days.append(candidate)
        offset += 1
    return days


def _seed(days: list[date]) -> None:
    TradingCalendarRepository().upsert_many(
        days, source="test", upstream_source="test"
    )
    repository = MarketRepository()
    for index, day in enumerate(days):
        # 成交额始终 1 万亿（稳定的量能），两融持续上升（流动性转强）
        repository.upsert_turnover(
            [
                MarketTurnover(
                    trade_date=day, exchange=Exchange.SSE,
                    turnover_amount=Decimal(str(5e11)),
                    turnover_rate_pct=Decimal("1.20"),
                    source_meta=_meta("sse"),
                ),
                MarketTurnover(
                    trade_date=day, exchange=Exchange.SZSE,
                    turnover_amount=Decimal(str(5e11)),
                    turnover_rate_pct=None,
                    source_meta=_meta("szse"),
                ),
            ]
        )
        balance = 1.0e12 + index * 1.5e10
        repository.upsert_margin(
            [
                MarginBalance(
                    trade_date=day, exchange=Exchange.SSE,
                    margin_balance=Decimal(str(balance)), source_meta=_meta("sse"),
                ),
                MarginBalance(
                    trade_date=day, exchange=Exchange.SZSE,
                    margin_balance=Decimal(str(balance * 0.9)), source_meta=_meta("szse"),
                ),
            ]
        )


def test_backfill_writes_one_row_per_trading_day(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "database_path", tmp_path / "etf.duckdb")
    run_migrations()
    days = _trading_days(12)
    _seed(days)

    result = backfill_pulse_history()

    assert result["rows_written"] == len(days)
    with connect(settings.database_path) as con:
        rows = con.execute(
            "SELECT trade_date, liquidity_state, volume_state, etf_state, overall_state,"
            " margin_balance_total, turnover_amount_total"
            " FROM mart.market_pulse_daily ORDER BY trade_date"
        ).fetchall()

    assert [row[0] for row in rows] == days

    # 第一层：两融持续上升 → 5 日变化率转强（位置分位样本不足只留空，不硬算）
    assert rows[-1][1] == "STRONG"
    # 第二层：成交额平坦 → 量比 1.0，判为中性
    assert rows[-1][2] == "NEUTRAL"
    # 第三层：没有篮子成员/申赎数据 → 如实 UNKNOWN
    assert rows[-1][3] == "UNKNOWN"
    # 综合：已知层只有两层，按文档规则 =1 个 STRONG → 中性观望
    assert rows[-1][4] == "中性观望"

    # 每一天只用到当天为止的两融（不能偷看后面）
    balances = [row[5] for row in rows]
    assert balances[0] < balances[-1]
    assert len(set(balances)) == len(days)


def test_backfill_is_idempotent(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "database_path", tmp_path / "etf.duckdb")
    run_migrations()
    _seed(_trading_days(10))

    first = backfill_pulse_history()
    with connect(settings.database_path) as con:
        before = con.execute(
            "SELECT trade_date, liquidity_state, volume_state, overall_state"
            " FROM mart.market_pulse_daily ORDER BY trade_date"
        ).fetchall()
    second = backfill_pulse_history()
    with connect(settings.database_path) as con:
        after = con.execute(
            "SELECT trade_date, liquidity_state, volume_state, overall_state"
            " FROM mart.market_pulse_daily ORDER BY trade_date"
        ).fetchall()

    assert first["rows_written"] == second["rows_written"] == 10
    assert before == after
