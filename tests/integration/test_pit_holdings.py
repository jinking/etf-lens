"""持仓 PIT：只使用 as-of 当时已经披露的那一期。"""

from datetime import date, datetime
from decimal import Decimal

from etf_engine.config.settings import settings
from etf_engine.db.migrate import run_migrations
from etf_engine.domain.enums import QualityStatus
from etf_engine.domain.models import ETFHolding, SourceMeta
from etf_engine.repositories.holding_repository import HoldingRepository

T1 = date(2026, 3, 31)
T2 = date(2026, 6, 30)
ASOF = date(2026, 6, 1)  # 介于两期之间


def _meta() -> SourceMeta:
    return SourceMeta(
        source="test", fetched_at=datetime(2026, 9, 12), quality_status=QualityStatus.PASS
    )


def _prepare(tmp_path, monkeypatch, *, with_disclosure_date: bool) -> None:
    monkeypatch.setattr(settings, "database_path", tmp_path / "etf.duckdb")
    run_migrations()
    repository = HoldingRepository()
    repository.upsert_many(
        [
            ETFHolding(
                etf_id="510300.SH",
                report_date=T1,
                disclosure_date=T1 if with_disclosure_date else None,
                stock_id="600519.SH",
                stock_name="贵州茅台",
                weight_pct=Decimal("5.0"),
                source_meta=_meta(),
            ),
            ETFHolding(
                etf_id="510300.SH",
                report_date=T2,
                disclosure_date=T2 if with_disclosure_date else None,
                stock_id="300750.SZ",
                stock_name="宁德时代",
                weight_pct=Decimal("9.0"),
                source_meta=_meta(),
            ),
        ]
    )


def test_asof_returns_the_earlier_disclosure(tmp_path, monkeypatch):
    _prepare(tmp_path, monkeypatch, with_disclosure_date=True)

    holdings, report_date, confidence = HoldingRepository().get_top10_asof("510300.SH", ASOF)

    assert report_date == T1, "6 月 1 日只能看到 3 月 31 日那一期"
    assert [item["stock_name"] for item in holdings] == ["贵州茅台"]
    assert confidence == "exact", "有披露日期 → 置信度 exact"


def test_later_disclosure_is_not_visible_before_it_exists(tmp_path, monkeypatch):
    _prepare(tmp_path, monkeypatch, with_disclosure_date=True)

    _, report_date, _ = HoldingRepository().get_top10_asof("510300.SH", date(2026, 12, 31))

    assert report_date == T2, "到了年底才看得到 6 月 30 日那一期"


def test_without_disclosure_date_confidence_is_limited(tmp_path, monkeypatch):
    """只有报告期、没有披露日时，只能标记为 limited——报告期结束不代表当天已公开。"""
    _prepare(tmp_path, monkeypatch, with_disclosure_date=False)

    holdings, report_date, confidence = HoldingRepository().get_top10_asof("510300.SH", ASOF)

    assert report_date == T1
    assert len(holdings) == 1
    assert confidence == "limited"


def test_disclosure_date_after_asof_hides_the_period(tmp_path, monkeypatch):
    """报告期已过、但披露日晚于 as-of → 该期对它不可见。"""
    _prepare(tmp_path, monkeypatch, with_disclosure_date=False)
    repository = HoldingRepository()
    repository.upsert_many(
        [
            ETFHolding(
                etf_id="510300.SH",
                report_date=T2,
                disclosure_date=date(2026, 8, 20),  # 8 月才披露
                stock_id="300750.SZ",
                stock_name="宁德时代",
                weight_pct=Decimal("9.0"),
                source_meta=_meta(),
            )
        ]
    )

    _, report_date, _ = HoldingRepository().get_top10_asof("510300.SH", ASOF)

    assert report_date == T1, "8 月披露的 6 月持仓，在 6 月 1 日不可见"
