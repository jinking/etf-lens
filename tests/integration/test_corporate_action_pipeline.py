"""公司行为端到端：折算不再制造假收益 / 假申赎 / 假跟踪误差。"""

from datetime import date, datetime, timedelta
from decimal import Decimal

from etf_engine.audit.data_rules import run_data_rules
from etf_engine.config.settings import settings
from etf_engine.db.connection import connect
from etf_engine.db.migrate import run_migrations
from etf_engine.domain.enums import CorporateActionType, QualityStatus
from etf_engine.domain.models import (
    ETFCorporateAction,
    ETFMaster,
    ETFNav,
    ETFQuote,
    ETFShare,
    IndexQuote,
    SourceMeta,
)
from etf_engine.jobs.compute_adjusted_series import compute_adjusted_series
from etf_engine.jobs.compute_mart import compute_mart
from etf_engine.repositories.corporate_action_repository import CorporateActionRepository
from etf_engine.repositories.index_repository import IndexRepository
from etf_engine.repositories.master_repository import MasterRepository
from etf_engine.repositories.nav_repository import NavRepository
from etf_engine.repositories.quote_repository import QuoteRepository
from etf_engine.repositories.share_repository import ShareRepository
from etf_engine.repositories.trading_calendar_repository import TradingCalendarRepository

SECURITY_ID = "515880.SH"
FETCHED_AT = datetime(2026, 9, 12, 18, 0)

#: 30 个交易日；第 16 天做 2:1 份额分拆（净值与价格减半）。
BASE = date(2026, 7, 1)
DAYS = [
    BASE + timedelta(days=offset)
    for offset in range(45)
    if (BASE + timedelta(days=offset)).weekday() < 5
][:30]
SPLIT_DAY = DAYS[15]


def _meta(upstream: str = "test") -> SourceMeta:
    return SourceMeta(
        source="test",
        upstream_source=upstream,
        fetched_at=FETCHED_AT,
        quality_status=QualityStatus.PASS,
    )


def _prepare(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "database_path", tmp_path / "etf.duckdb")
    run_migrations()

    calendar_days = [
        date(2026, 1, 1) + timedelta(days=offset)
        for offset in range(365)
        if (date(2026, 1, 1) + timedelta(days=offset)).weekday() < 5
    ]
    TradingCalendarRepository().upsert_many(calendar_days, source="test", upstream_source="test")
    MasterRepository().upsert_many(
        [
            ETFMaster(
                security_id=SECURITY_ID,
                ticker="515880",
                exchange="SSE",
                fund_name="通信ETF",
                tracking_index_id="000300",
                tracking_index_name="沪深300指数",
                source_meta=_meta(),
            )
        ]
    )

    quotes: list[ETFQuote] = []
    shares: list[ETFShare] = []
    navs: list[ETFNav] = []
    index_quotes: list[IndexQuote] = []
    for offset, trade_date in enumerate(DAYS):
        # 折算日：净值/份额当天生效；价格从次一交易日生效（实测约定）
        price = Decimal("1.5") if trade_date <= SPLIT_DAY else Decimal("0.75")
        nav = Decimal("1.5") if trade_date < SPLIT_DAY else Decimal("0.75")
        shares_now = (
            Decimal(str(1000 + offset))
            if trade_date < SPLIT_DAY
            else Decimal(str(1000 + offset)) * 2
        )
        quotes.append(
            ETFQuote(
                security_id=SECURITY_ID,
                trade_date=trade_date,
                close=price,
                turnover_amount=Decimal("1000000"),
                source_meta=_meta("sina"),
            )
        )
        shares.append(
            ETFShare(
                security_id=SECURITY_ID,
                trade_date=trade_date,
                shares=shares_now,
                nav=nav,
                nav_source="test",
                source_meta=_meta("sse"),
            )
        )
        navs.append(
            ETFNav(
                security_id=SECURITY_ID,
                nav_date=trade_date,
                unit_nav=nav,
                source_meta=_meta("eastmoney"),
            )
        )
        index_quotes.append(
            IndexQuote(
                index_id="000300",
                trade_date=trade_date,
                close=Decimal(4000 + offset),
                source_meta=_meta("sina"),
            )
        )

    QuoteRepository().upsert_many(quotes)
    ShareRepository().upsert_many(shares)
    NavRepository().upsert_many(navs)
    IndexRepository().upsert_quotes(index_quotes)
    CorporateActionRepository().upsert_many(
        [
            ETFCorporateAction(
                security_id=SECURITY_ID,
                action_date=SPLIT_DAY,
                action_type=CorporateActionType.SPLIT,
                split_ratio="1:2.0000",
                share_adjustment_factor=Decimal(2),
                nav_adjustment_factor=Decimal("0.5"),
                source_meta=_meta("eastmoney_fund_dividend"),
            )
        ]
    )


def test_split_no_longer_creates_fake_returns_or_subscriptions(tmp_path, monkeypatch):
    _prepare(tmp_path, monkeypatch)

    compute_adjusted_series(security_ids=[SECURITY_ID])
    compute_mart(security_ids=[SECURITY_ID])

    with connect(settings.database_path) as con:
        v1 = con.execute(
            """
            SELECT return_1d, return_20d FROM mart.etf_metric_daily
            WHERE security_id = ? AND calculation_version = 'metric_v1'
            """,
            [SECURITY_ID],
        ).fetchone()
        v2 = con.execute(
            """
            SELECT return_1d, return_20d FROM mart.etf_metric_daily
            WHERE security_id = ? AND calculation_version = 'metric_v2'
            """,
            [SECURITY_ID],
        ).fetchone()
        flow_v1 = con.execute(
            """
            SELECT share_change_1d FROM mart.etf_flow_daily
            WHERE security_id = ? AND calculation_version = 'flow_v1'
            """,
            [SECURITY_ID],
        ).fetchone()
        flow_v2 = con.execute(
            """
            SELECT share_change_1d, flow_quality_status, calculation_version
            FROM mart.etf_flow_daily
            WHERE security_id = ? AND calculation_version = 'flow_v2'
            """,
            [SECURITY_ID],
        ).fetchone()

    # v1：1 日窗口不含折算 → 正常给 0；20 日窗口跨折算 → 拒绝计算（NULL），
    # 而不是给出假的 -50%
    assert v1[0] == 0.0
    assert v1[1] is None
    # v2：复权后序列连续 → 20 日收益也能算出来（期间价格无真实涨跌）
    assert v2[0] == 0.0
    assert v2[1] is not None
    # 最新一天不在折算日：v1 与 v2 必须完全一致（v2 只修正被污染的部分）。
    # 折算日当天的"假巨额申购"由单测与自检规则覆盖：
    # 连续窗口里 compute_mart 只写最新一行，折算日那行要靠逐日回放才看得到。
    assert flow_v1[0] == 2.0
    assert flow_v2[0] == 2.0
    assert flow_v2[1] == "corporate_action_adjusted"
    assert flow_v2[2] == "flow_v2"


def test_adjusted_series_is_point_in_time_safe(tmp_path, monkeypatch):
    _prepare(tmp_path, monkeypatch)
    compute_adjusted_series(security_ids=[SECURITY_ID])

    with connect(settings.database_path) as con:
        before = con.execute(
            """
            SELECT adjustment_factor, adjusted_close FROM mart.etf_adjusted_daily
            WHERE security_id = ? AND trade_date = ?
            """,
            [SECURITY_ID, DAYS[14]],
        ).fetchone()
        after = con.execute(
            """
            SELECT adjustment_factor, adjusted_close FROM mart.etf_adjusted_daily
            WHERE security_id = ? AND trade_date = ?
            """,
            [SECURITY_ID, DAYS[16]],
        ).fetchone()

    assert before[0] == 1.0, "折算之前的因子不受未来事件影响"
    assert after[0] == 2.0
    # 复权后价格连续：1.5 vs 0.75×2
    assert before[1] == 1.5
    assert after[1] == 1.5


def test_audit_flags_unadjusted_flow_across_a_split(tmp_path, monkeypatch):
    """折算窗口内只有 v1 口径（没有 v2）→ 自检必须报出来。"""
    _prepare(tmp_path, monkeypatch)
    compute_adjusted_series(security_ids=[SECURITY_ID])
    compute_mart(security_ids=[SECURITY_ID])

    results = {item["name"]: item for item in run_data_rules()}
    # v1 与 v2 并存是设计：可读口径里有 v2，不算违规
    assert results["unadjusted_flow_crosses_corporate_action"]["count"] == 0

    # 复权序列本身是干净的
    assert results["adjusted_series_missing_version"]["count"] == 0
    assert results["adjusted_series_future_action_leak"]["count"] == 0

    # 把 v2 口径删掉（模拟"折算后没重算"）→ 规则必须报出来
    with connect(settings.database_path) as con:
        con.execute("DELETE FROM mart.etf_flow_daily WHERE calculation_version = 'flow_v2'")

    check = {item["name"]: item for item in run_data_rules()}[
        "unadjusted_flow_crosses_corporate_action"
    ]
    assert check["count"] >= 1
    assert "机械份额变化会被误读成申赎" in check["violations"][0]["detail"]
