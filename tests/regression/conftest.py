"""回归基线用的确定性数据仓库。

目标不是覆盖新功能，而是把**当前行为**钉死：V2 重构（Point-in-Time、复权序列、
同类分组）会故意改变输出契约，但任何**非预期**的变化都应该被这几个快照测试抓住。

种子数据是手工构造的，规模小到可以口算：

```text
3 只 ETF × 25 个交易日
  510300.SH 沪深300ETF   跟踪 000300，管理费 0.15%，份额 1000 + 10i，净值 1.5
  159919.SZ 沪深300ETF   跟踪 000300，管理费 0.20%，份额 2000 + 20i，净值 1.5
  588200.SH 科创芯片ETF  跟踪 931160，管理费 0.50%，有持仓与行业标签
收盘价 100 + i，成交额 1,000,000 + 1,000i，指数 000300 = 1000 + 5i
```
"""

from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest

from etf_engine.config.settings import settings
from etf_engine.db.migrate import run_migrations
from etf_engine.domain.enums import QualityStatus
from etf_engine.domain.models import (
    ETFHolding,
    ETFMaster,
    ETFNav,
    ETFQuote,
    ETFShare,
    IndexQuote,
    SourceMeta,
)
from etf_engine.jobs.compute_adjusted_series import compute_adjusted_series
from etf_engine.jobs.compute_mart import compute_mart
from etf_engine.repositories.holding_repository import HoldingRepository
from etf_engine.repositories.index_repository import IndexRepository
from etf_engine.repositories.master_repository import MasterRepository
from etf_engine.repositories.nav_repository import NavRepository
from etf_engine.repositories.quote_repository import QuoteRepository
from etf_engine.repositories.share_repository import ShareRepository
from etf_engine.repositories.tag_repository import TagRepository
from etf_engine.repositories.trading_calendar_repository import TradingCalendarRepository

FETCHED_AT = datetime(2026, 9, 12, 18, 0)

#: 25 个交易日，最后一天是 2026-09-11（周五）。
TRADING_DAYS = [
    date(2026, 8, 7) + timedelta(days=offset)
    for offset in range(36)
    if (date(2026, 8, 7) + timedelta(days=offset)).weekday() < 5
][:25]
ASOF_DATE = TRADING_DAYS[-1]

UNIVERSE = {
    "510300.SH": {"index_id": "000300", "fee": Decimal("0.15"), "share_base": 1000, "step": 10},
    "159919.SZ": {"index_id": "000300", "fee": Decimal("0.20"), "share_base": 2000, "step": 20},
    "588200.SH": {"index_id": "931160", "fee": Decimal("0.50"), "share_base": 500, "step": 5},
}

MONEY = Decimal("1500000000")


def _meta(upstream: str = "test") -> SourceMeta:
    return SourceMeta(
        source="test",
        upstream_source=upstream,
        fetched_at=FETCHED_AT,
        quality_status=QualityStatus.PASS,
    )


def seed_warehouse() -> None:
    """写入确定性数据并跑一次 compute_mart。"""
    calendar_days = [
        date(2026, 1, 1) + timedelta(days=offset)
        for offset in range(365)
        if (date(2026, 1, 1) + timedelta(days=offset)).weekday() < 5
    ]
    TradingCalendarRepository().upsert_many(calendar_days, source="test", upstream_source="test")

    masters: list[ETFMaster] = []
    quotes: list[ETFQuote] = []
    shares: list[ETFShare] = []
    navs: list[ETFNav] = []
    tags: list[dict] = []

    for security_id, spec in UNIVERSE.items():
        ticker, _, suffix = security_id.partition(".")
        masters.append(
            ETFMaster(
                security_id=security_id,
                ticker=ticker,
                exchange="SSE" if suffix == "SH" else "SZSE",
                fund_name=f"{security_id} 基金",
                short_name=f"{ticker}ETF",
                manager_name="测试基金公司",
                established_date=date(2015, 5, 6),
                management_fee_pct=spec["fee"],
                tracking_index_id=spec["index_id"],
                tracking_index_name="测试指数",
                reported_aum=MONEY,
                source_meta=_meta(),
            )
        )
        for offset, trade_date in enumerate(TRADING_DAYS):
            quotes.append(
                ETFQuote(
                    security_id=security_id,
                    trade_date=trade_date,
                    name=f"{ticker}ETF",
                    open=Decimal(100 + offset),
                    high=Decimal(101 + offset),
                    low=Decimal(99 + offset),
                    close=Decimal(100 + offset),
                    turnover_amount=Decimal(1_000_000 + offset * 1000),
                    source_meta=_meta("sina"),
                )
            )
            shares.append(
                ETFShare(
                    security_id=security_id,
                    trade_date=trade_date,
                    shares=Decimal(spec["share_base"] + offset * spec["step"]),
                    nav=Decimal("1.5"),
                    nav_source="test",
                    source_meta=_meta("sse"),
                )
            )
            navs.append(
                ETFNav(
                    security_id=security_id,
                    nav_date=trade_date,
                    unit_nav=Decimal("1.5"),
                    adjusted_nav=None,
                    source_meta=_meta("eastmoney"),
                )
            )

    MasterRepository().upsert_many(masters)
    QuoteRepository().upsert_many(quotes)
    ShareRepository().upsert_many(shares)
    NavRepository().upsert_many(navs)

    index_repository = IndexRepository()
    index_repository.upsert_catalog(
        [
            _catalog_entry("000300", "沪深300指数", "sh000300"),
            _catalog_entry("931160", "中证全指通信设备指数", None),
        ]
    )
    index_repository.upsert_map(
        [
            {
                "etf_id": "510300.SH",
                "index_id": "000300",
                "index_name": "沪深300指数",
                "valid_from": TRADING_DAYS[0],
                "source": "fund_benchmark",
            },
            {
                "etf_id": "159919.SZ",
                "index_id": "000300",
                "index_name": "沪深300指数",
                "valid_from": TRADING_DAYS[0],
                "source": "fund_benchmark",
            },
            {
                "etf_id": "588200.SH",
                "index_id": "931160",
                "index_name": "中证全指通信设备指数",
                "valid_from": TRADING_DAYS[0],
                "source": "fund_benchmark",
            },
        ]
    )
    index_repository.upsert_quotes(
        [
            IndexQuote(
                index_id="000300",
                trade_date=trade_date,
                open=Decimal(1000 + 5 * offset),
                high=Decimal(1001 + 5 * offset),
                low=Decimal(999 + 5 * offset),
                close=Decimal(1000 + 5 * offset),
                source_meta=_meta("sina"),
            )
            for offset, trade_date in enumerate(TRADING_DAYS)
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
    tags.append(
        {
            "etf_id": "588200.SH",
            "tag": "集成电路",
            "tag_type": "industry",
            "confidence": 0.72,
            "coverage": 0.95,
            "calculation_version": "tag_v1",
            "valid_from": date(2026, 6, 30),
        }
    )
    TagRepository().upsert_tags(tags)

    # 生产口径是 v2（metric_v2 / flow_v2），因此夹具也必须先建复权序列，
    # 否则研究查询按显式版本过滤后取不到任何行。
    compute_adjusted_series()
    compute_mart()


def _catalog_entry(index_id: str, name: str, symbol: str | None):
    from etf_engine.domain.models import IndexCatalogEntry

    return IndexCatalogEntry(
        index_id=index_id,
        index_name=name,
        market_symbol=symbol,
        source_meta=_meta("csindex"),
    )


@pytest.fixture
def warehouse(tmp_path, monkeypatch) -> str:
    """确定性仓库：返回 as-of 日期字符串。"""
    monkeypatch.setattr(settings, "database_path", tmp_path / "etf.duckdb")
    monkeypatch.setattr(settings, "raw_path", tmp_path / "raw")
    run_migrations()
    seed_warehouse()
    return ASOF_DATE.isoformat()


@pytest.fixture
def warehouse_db(tmp_path, monkeypatch):
    """同上，但返回数据库路径（给直接吃路径的 API 用）。"""
    monkeypatch.setattr(settings, "database_path", tmp_path / "etf.duckdb")
    monkeypatch.setattr(settings, "raw_path", tmp_path / "raw")
    run_migrations()
    seed_warehouse()
    return tmp_path / "etf.duckdb"
