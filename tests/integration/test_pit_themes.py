"""主题聚合 PIT 过滤集成测试。

验证 ResearchRepository.themes() 严格按 Tag 的 valid_from / valid_to 过滤，
历史 as-of 查询不得包含未来才生效的标签。
"""

from datetime import date, datetime
from decimal import Decimal

from etf_engine.config.settings import settings
from etf_engine.db.migrate import run_migrations
from etf_engine.domain.enums import QualityStatus
from etf_engine.domain.models import ETFMaster, ETFQuote, ETFShare, SourceMeta
from etf_engine.domain.research_context import ResearchContext
from etf_engine.repositories.master_repository import MasterRepository
from etf_engine.repositories.quote_repository import QuoteRepository
from etf_engine.repositories.research_repository import ResearchRepository
from etf_engine.repositories.share_repository import ShareRepository
from etf_engine.repositories.tag_repository import TagRepository
from etf_engine.repositories.trading_calendar_repository import TradingCalendarRepository

T1 = date(2026, 9, 1)
T2 = date(2026, 9, 15)
FETCHED_AT = datetime(2026, 9, 1, 10, 0)


def _meta() -> SourceMeta:
    return SourceMeta(source="test", fetched_at=FETCHED_AT, quality_status=QualityStatus.PASS)


def test_themes_filters_by_tag_valid_from_and_valid_to(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "database_path", tmp_path / "etf.duckdb")
    run_migrations()
    TradingCalendarRepository().upsert_many([T1, T2], source="test", upstream_source="test")

    sec1, sec2 = "510300.SH", "159919.SZ"
    MasterRepository().upsert_many(
        [
            ETFMaster(
                security_id=sec1,
                ticker="510300",
                exchange="SSE",
                fund_name="300ETF",
                source_meta=_meta(),
            ),
            ETFMaster(
                security_id=sec2,
                ticker="159919",
                exchange="SZSE",
                fund_name="300ETF",
                source_meta=_meta(),
            ),
        ]
    )
    QuoteRepository().upsert_many(
        [
            ETFQuote(
                security_id=sec,
                trade_date=T1,
                close=Decimal("1.0"),
                turnover_amount=Decimal("100000"),
                source_meta=_meta(),
            )
            for sec in (sec1, sec2)
        ]
    )
    ShareRepository().upsert_many(
        [
            ETFShare(
                security_id=sec,
                trade_date=T1,
                shares=Decimal("100000"),
                nav=Decimal("1.0"),
                source_meta=_meta(),
            )
            for sec in (sec1, sec2)
        ]
    )

    # sec1 在 T1 有标签 "新能源"；sec2 在 T2 才打上标签 "半导体"
    TagRepository().upsert_tags(
        [
            {
                "etf_id": sec1,
                "tag": "新能源",
                "tag_type": "industry",
                "source": "test",
                "valid_from": T1,
                "valid_to": None,
            },
            {
                "etf_id": sec2,
                "tag": "半导体",
                "tag_type": "industry",
                "source": "test",
                "valid_from": T2,
                "valid_to": None,
            },
        ]
    )

    repo = ResearchRepository()
    themes_t1 = repo.themes(context=ResearchContext(asof_date=T1))
    theme_names_t1 = [item["theme"] for item in themes_t1]

    assert "新能源" in theme_names_t1
    assert "半导体" not in theme_names_t1, "T1 查询不得泄露 T2 才生效的 半导体 标签"

    # T2 查询两者皆有
    themes_t2 = repo.themes(context=ResearchContext(asof_date=T2))
    theme_names_t2 = [item["theme"] for item in themes_t2]
    assert "新能源" in theme_names_t2
    assert "半导体" in theme_names_t2
