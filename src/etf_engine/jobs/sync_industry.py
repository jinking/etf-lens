import time
from functools import partial

from etf_engine.config.settings import settings
from etf_engine.db.connection import connect
from etf_engine.domain.identifiers import SecurityId
from etf_engine.domain.quality import DataQualityIssue, error
from etf_engine.ingestion.retry import with_retry
from etf_engine.ingestion.run_recorder import IngestionRunRecorder
from etf_engine.ingestion.source_health import track_source_health
from etf_engine.repositories.quality_issue_repository import QualityIssueRepository
from etf_engine.repositories.stock_industry_repository import StockIndustryRepository
from etf_engine.sources.registry import registry

DEFAULT_SLEEP_SECONDS = 0.2


def _holding_targets() -> list[str]:
    """默认只取"已被 ETF 披露持仓覆盖"的个股：够用且有界。"""
    with connect(settings.database_path) as con:
        rows = con.execute(
            "SELECT DISTINCT stock_id FROM core.etf_holding_disclosure ORDER BY stock_id"
        ).fetchall()
    return [row[0] for row in rows]


def sync_industry(
    security_ids: list[str] | None = None,
    sleep_seconds: float = DEFAULT_SLEEP_SECONDS,
) -> dict:
    """同步个股行业分类到 ``core.stock_industry``。"""
    source = registry.industry_source()
    repository = StockIndustryRepository()
    quality = QualityIssueRepository()
    recorder = IngestionRunRecorder()

    if security_ids:
        targets: list[str] = []
        for item in security_ids:
            try:
                targets.append(SecurityId.parse(item).value)
            except ValueError:
                continue
    else:
        targets = _holding_targets()

    if not targets:
        return {"status": "SKIPPED", "reason": "没有可同步的个股（先跑 sync-holdings）"}

    run_id = recorder.start("stock_industry", "cninfo", None)
    industries: list = []
    issues: list[DataQualityIssue] = []
    failures = 0

    for security_id in targets:
        try:
            with track_source_health("cninfo", "stock_industry"):
                fetched, fetch_issues = with_retry(
                    partial(source.fetch_industries, [security_id])
                )
        except Exception as exc:
            failures += 1
            issues.append(error("industry_fetch_failed", f"{security_id}: {exc}"))
            continue
        industries.extend(fetched)
        issues.extend(fetch_issues)
        if sleep_seconds:
            time.sleep(sleep_seconds)

    written = repository.upsert_many(industries)
    issues_written = quality.record(dataset="stock_industry", issues=issues)
    status = "SUCCESS" if failures == 0 else ("PARTIAL" if industries else "FAILED")
    recorder.finish(
        run_id,
        status=status,
        rows_fetched=len(targets),
        rows_written=written,
        rows_rejected=failures,
        error_message=None if failures == 0 else f"{failures} 只个股同步失败",
    )

    return {
        "run_id": run_id,
        "status": status,
        "target_count": len(targets),
        "rows_written": written,
        "unmapped": len(targets) - len(industries),
        "quality_issues": issues_written,
    }
