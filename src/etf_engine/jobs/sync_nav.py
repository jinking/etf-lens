from datetime import date

from etf_engine.config.settings import settings
from etf_engine.ingestion.raw_store import RawSnapshotStore
from etf_engine.ingestion.run_recorder import IngestionRunRecorder
from etf_engine.repositories.nav_repository import NavRepository
from etf_engine.repositories.quality_issue_repository import QualityIssueRepository
from etf_engine.sources.registry import registry


def sync_nav(trade_date: date | None = None) -> dict:
    """同步 ETF 单位净值到 ``core.etf_nav_daily``。

    净值是份额→规模估算与跟踪误差的前置事实；上游一次返回最近两个交易日，
    因此每次运行都会同时补齐前一日，历史由每日运行持续积累。
    """
    source = registry.nav_source()
    repository = NavRepository()
    quality = QualityIssueRepository()
    raw_store = RawSnapshotStore(settings.raw_path)
    recorder = IngestionRunRecorder()
    run_id = recorder.start("etf_nav", "akshare", trade_date)

    try:
        navs, issues = source.fetch_navs_with_issues(trade_date=trade_date)

        if navs:
            raw_store.write_records(
                source="akshare",
                dataset="etf_nav",
                trade_date=navs[-1].nav_date,
                records=[nav.model_dump(mode="json") for nav in navs],
            )

        for nav in navs:
            nav.source_meta.ingestion_run_id = run_id

        written = repository.upsert_many(navs)
        issues_written = quality.record(
            dataset="etf_nav",
            issues=issues,
            trade_date=trade_date,
        )
        recorder.finish(
            run_id,
            status="SUCCESS",
            rows_fetched=len(navs),
            rows_written=written,
            rows_rejected=0,
        )
        return {
            "run_id": run_id,
            "rows_fetched": len(navs),
            "rows_written": written,
            "quality_issues": issues_written,
        }
    except Exception as exc:
        recorder.finish(
            run_id,
            status="FAILED",
            rows_fetched=0,
            rows_written=0,
            rows_rejected=0,
            error_message=str(exc),
        )
        raise
