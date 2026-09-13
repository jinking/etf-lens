"""同步 ETF 公司行为（拆分/折算/分红）事实。

逐只基金请求披露页，因此是有界、限速、可续跑的任务。没有披露来源的标的
保持为空——**绝不用价格跳变反推**公司行为。
"""

import time
from functools import partial

from etf_engine.config.settings import settings
from etf_engine.db.connection import connect
from etf_engine.domain.identifiers import SecurityId
from etf_engine.domain.quality import DataQualityIssue, error
from etf_engine.ingestion.retry import with_retry
from etf_engine.ingestion.run_recorder import IngestionRunRecorder
from etf_engine.ingestion.source_health import track_source_health
from etf_engine.repositories.corporate_action_repository import CorporateActionRepository
from etf_engine.repositories.quality_issue_repository import QualityIssueRepository
from etf_engine.sources.registry import registry

DEFAULT_SLEEP_SECONDS = 0.3


def _action_targets(security_ids: list[str] | None, limit: int | None) -> list[str]:
    """默认：有份额历史的 ETF 按规模从大到小（公司行为只会出现在有份额的标的上）。"""
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
    SELECT security_id FROM latest_share
    WHERE rn = 1
    ORDER BY estimated_aum DESC NULLS LAST, security_id
    """
    values: list = []
    if limit is not None:
        sql += " LIMIT ?"
        values.append(limit)
    with connect(settings.database_path) as con:
        return [row[0] for row in con.execute(sql, values).fetchall()]


def sync_corporate_actions(
    security_ids: list[str] | None = None,
    limit: int | None = 50,
    sleep_seconds: float = DEFAULT_SLEEP_SECONDS,
) -> dict:
    source = registry.corporate_action_source()
    repository = CorporateActionRepository()
    quality = QualityIssueRepository()
    recorder = IngestionRunRecorder()

    targets = _action_targets(security_ids, limit)
    if not targets:
        return {"status": "SKIPPED", "reason": "没有需要同步公司行为的 ETF"}

    run_id = recorder.start("etf_corporate_action", "eastmoney_fund_dividend", None)
    total_actions = 0
    fetched_funds = 0
    failures = 0
    issues: list[DataQualityIssue] = []

    for security_id in targets:
        try:
            with track_source_health("eastmoney", "etf_corporate_action"):
                actions, source_issues = with_retry(
                    partial(source.fetch_corporate_actions_with_issues, security_id)
                )
        except Exception as exc:
            failures += 1
            issues.append(error("corporate_action_fetch_failed", f"{security_id}: {exc}"))
            continue

        for action in actions:
            action.source_meta.ingestion_run_id = run_id
        fetched_funds += 1
        total_actions += repository.upsert_many(actions)
        issues.extend(source_issues)
        if sleep_seconds:
            time.sleep(sleep_seconds)

    issues_written = quality.record(dataset="etf_corporate_action", issues=issues)
    status = "SUCCESS" if failures == 0 else ("PARTIAL" if fetched_funds else "FAILED")
    recorder.finish(
        run_id,
        status=status,
        rows_fetched=fetched_funds,
        rows_written=total_actions,
        rows_rejected=failures,
    )
    return {
        "run_id": run_id,
        "status": status,
        "target_count": len(targets),
        "funds_fetched": fetched_funds,
        "actions_written": total_actions,
        "failures": failures,
        "quality_issues": issues_written,
    }
