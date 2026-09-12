import time
from datetime import datetime, timedelta
from functools import partial

from etf_engine.config.settings import settings
from etf_engine.db.connection import connect
from etf_engine.domain.identifiers import SecurityId
from etf_engine.domain.quality import DataQualityIssue, error
from etf_engine.ingestion.retry import with_retry
from etf_engine.ingestion.run_recorder import IngestionRunRecorder
from etf_engine.ingestion.source_health import track_source_health
from etf_engine.jobs.sync_calendar import ensure_market_calendar
from etf_engine.repositories.nav_repository import NavRepository
from etf_engine.repositories.quality_issue_repository import QualityIssueRepository
from etf_engine.sources.registry import registry

#: 逐只基金请求之间的间隔，避免对上游发压。
DEFAULT_SLEEP_SECONDS = 0.3


def _resolve_targets(
    security_ids: list[str] | None,
    days: int,
    limit: int | None,
) -> list[str]:
    """确定需要回补净值的 ETF：优先规模大、且净值历史不足的。"""
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
    ),
    nav_depth AS (
        SELECT security_id, COUNT(*) AS nav_days
        FROM core.etf_nav_daily
        GROUP BY security_id
    )
    SELECT s.security_id
    FROM latest_share s
    LEFT JOIN nav_depth n ON n.security_id = s.security_id
    WHERE s.rn = 1
      AND COALESCE(n.nav_days, 0) < ?
    ORDER BY s.estimated_aum DESC NULLS LAST, s.security_id
    """
    values: list = [days]
    if limit is not None:
        sql += " LIMIT ?"
        values.append(limit)

    with connect(settings.database_path) as con:
        return [row[0] for row in con.execute(sql, values).fetchall()]


def backfill_nav(
    security_ids: list[str] | None = None,
    days: int = 60,
    limit: int | None = None,
    sleep_seconds: float = DEFAULT_SLEEP_SECONDS,
) -> dict:
    """逐只基金回补净值历史。

    净值历史接口没有全市场批量版本，因此这是有界、限速、可续跑的任务：
    默认只挑"净值历史不足 ``days`` 天"里规模最大的 ``limit`` 只。
    """
    source = registry.nav_history_source()
    repository = NavRepository()
    quality = QualityIssueRepository()
    recorder = IngestionRunRecorder()
    calendar = ensure_market_calendar()

    end_date = calendar.latest_closed_trading_day(datetime.now().astimezone())
    start_date = end_date - timedelta(days=days * 2)  # 自然日区间，足够覆盖交易日窗口
    targets = _resolve_targets(security_ids, days, limit)

    if not targets:
        return {"status": "SKIPPED", "reason": "没有需要回补净值的 ETF"}

    run_id = recorder.start("etf_nav_history", "akshare_eastmoney", end_date)
    total_fetched = 0
    total_written = 0
    issues: list[DataQualityIssue] = []
    failures = 0
    processed = 0

    for security_id in targets:
        try:
            with track_source_health("akshare/eastmoney", "etf_nav_history"):
                navs, source_issues = with_retry(
                    partial(
                        source.fetch_nav_history_with_issues,
                        security_id,
                        start_date=start_date,
                        end_date=end_date,
                    )
                )
        except Exception as exc:
            failures += 1
            issues.append(error("nav_history_fetch_failed", f"{security_id}: {exc}"))
            continue

        processed += 1
        issues.extend(source_issues)
        for nav in navs:
            nav.source_meta.ingestion_run_id = run_id
        total_fetched += len(navs)
        total_written += repository.upsert_many(navs)

        if sleep_seconds:
            time.sleep(sleep_seconds)

    issues_written = quality.record(dataset="etf_nav_history", issues=issues, trade_date=end_date)
    status = "SUCCESS" if failures == 0 else ("PARTIAL" if processed else "FAILED")
    recorder.finish(
        run_id,
        status=status,
        rows_fetched=total_fetched,
        rows_written=total_written,
        rows_rejected=failures,
        error_message=None if failures == 0 else f"{failures} 只基金回补失败",
    )

    return {
        "run_id": run_id,
        "status": status,
        "asof_date": end_date.isoformat(),
        "start_date": start_date.isoformat(),
        "target_count": len(targets),
        "funds_fetched": processed,
        "funds_failed": failures,
        "rows_fetched": total_fetched,
        "rows_written": total_written,
        "quality_issues": issues_written,
    }
