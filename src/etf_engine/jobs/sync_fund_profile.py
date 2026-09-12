"""基金档案补齐任务。

逐只基金请求档案页，因此是有界、限速、可续跑的：默认只处理 master 里
费率/成立日期/管理人仍然为空的 ETF，按规模从大到小。
"""

import time
from functools import partial

from etf_engine.config.settings import settings
from etf_engine.db.connection import connect
from etf_engine.domain.identifiers import SecurityId
from etf_engine.domain.quality import DataQualityIssue, error, warn
from etf_engine.ingestion.retry import with_retry
from etf_engine.ingestion.run_recorder import IngestionRunRecorder
from etf_engine.ingestion.source_health import track_source_health
from etf_engine.repositories.master_repository import MasterRepository
from etf_engine.repositories.quality_issue_repository import QualityIssueRepository
from etf_engine.sources.registry import registry

DEFAULT_SLEEP_SECONDS = 0.3


def _profile_targets(security_ids: list[str] | None, limit: int | None) -> list[str]:
    if security_ids:
        targets: list[str] = []
        for item in security_ids:
            try:
                targets.append(SecurityId.parse(item).value)
            except ValueError:
                continue
        return targets

    sql = """
    WITH latest_share AS (
        SELECT security_id, estimated_aum,
               ROW_NUMBER() OVER (PARTITION BY security_id ORDER BY trade_date DESC) AS rn
        FROM core.etf_share_daily
    )
    SELECT m.security_id
    FROM core.etf_master m
    LEFT JOIN latest_share s ON s.security_id = m.security_id AND s.rn = 1
    WHERE m.established_date IS NULL
       OR m.management_fee_pct IS NULL
       OR m.manager_name IS NULL
    ORDER BY s.estimated_aum DESC NULLS LAST, m.security_id
    """
    values: list = []
    if limit is not None:
        sql += " LIMIT ?"
        values.append(limit)
    with connect(settings.database_path) as con:
        return [row[0] for row in con.execute(sql, values).fetchall()]


def sync_fund_profile(
    security_ids: list[str] | None = None,
    limit: int | None = 50,
    sleep_seconds: float = DEFAULT_SLEEP_SECONDS,
) -> dict:
    source = registry.fund_profile_source()
    repository = MasterRepository()
    quality = QualityIssueRepository()
    recorder = IngestionRunRecorder()

    targets = _profile_targets(security_ids, limit)
    if not targets:
        return {"status": "SKIPPED", "reason": "没有需要补齐档案的 ETF"}

    run_id = recorder.start("fund_profile", "eastmoney_fund_profile", None)
    profiles: list = []
    issues: list[DataQualityIssue] = []
    failures = 0

    for security_id in targets:
        try:
            with track_source_health("eastmoney", "fund_profile"):
                profile = with_retry(partial(source.fetch_profile, security_id))
        except Exception as exc:
            failures += 1
            issues.append(error("fund_profile_fetch_failed", f"{security_id}: {exc}"))
            continue

        if profile.established_date is None and profile.management_fee_pct is None:
            issues.append(warn("fund_profile_incomplete", security_id))
        profiles.append(profile)
        if sleep_seconds:
            time.sleep(sleep_seconds)

    written = repository.enrich_from_profile(profiles)
    issues_written = quality.record(dataset="fund_profile", issues=issues)
    status = "SUCCESS" if failures == 0 else ("PARTIAL" if profiles else "FAILED")
    recorder.finish(
        run_id,
        status=status,
        rows_fetched=len(targets),
        rows_written=written,
        rows_rejected=failures,
    )
    return {
        "run_id": run_id,
        "status": status,
        "target_count": len(targets),
        "rows_written": written,
        "failures": failures,
        "quality_issues": issues_written,
    }
