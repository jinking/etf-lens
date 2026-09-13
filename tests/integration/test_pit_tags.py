"""标签 PIT：valid_from / valid_to 之外的状态不可见。"""

from datetime import date

from etf_engine.config.settings import settings
from etf_engine.db.migrate import run_migrations
from etf_engine.domain.research_context import ResearchContext
from etf_engine.repositories.tag_repository import TagRepository
from etf_engine.services.research_service import ResearchService

T1 = date(2026, 1, 1)
T2 = date(2026, 6, 1)
ASOF = date(2026, 3, 1)  # 介于 T1 与 T2 之间


def _prepare(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "database_path", tmp_path / "etf.duckdb")
    run_migrations()
    with __import__("etf_engine.db.connection", fromlist=["connect"]).connect(
        settings.database_path
    ) as con:
        con.execute(
            """
            INSERT INTO core.etf_master (security_id, ticker, exchange, fund_name)
            VALUES ('510300.SH', '510300', 'SSE', '沪深300ETF')
            """
        )
    TagRepository().upsert_tags(
        [
            {
                "etf_id": "510300.SH",
                "tag": "旧标签",
                "tag_type": "industry",
                "confidence": 0.9,
                "valid_from": T1,
                "valid_to": T2,  # 6 月起失效
            },
            {
                "etf_id": "510300.SH",
                "tag": "新标签",
                "tag_type": "industry",
                "confidence": 0.9,
                "valid_from": T2,
            },
        ]
    )


def test_tags_asof_returns_the_old_tag_before_the_switch(tmp_path, monkeypatch):
    _prepare(tmp_path, monkeypatch)

    tags = TagRepository().get_tags_asof("510300.SH", ASOF)

    assert [tag["tag"] for tag in tags] == ["旧标签"]


def test_tags_asof_returns_the_new_tag_after_the_switch(tmp_path, monkeypatch):
    _prepare(tmp_path, monkeypatch)

    tags = TagRepository().get_tags_asof("510300.SH", date(2026, 7, 1))

    assert [tag["tag"] for tag in tags] == ["新标签"]


def test_screener_by_tag_respects_asof(tmp_path, monkeypatch):
    """按标签筛选也必须走 as-of：历史日期不能用今天才生效的标签。"""
    _prepare(tmp_path, monkeypatch)

    old = ResearchService().screen(tag="旧标签", context=ResearchContext(asof_date=ASOF))
    new = ResearchService().screen(tag="新标签", context=ResearchContext(asof_date=ASOF))
    later = ResearchService().screen(
        tag="新标签", context=ResearchContext(asof_date=date(2026, 7, 1))
    )

    assert [row["security_id"] for row in old] == ["510300.SH"]
    assert new == [], "新标签在 3 月还没生效"
    assert [row["security_id"] for row in later] == ["510300.SH"]
