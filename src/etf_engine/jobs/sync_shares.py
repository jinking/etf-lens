from datetime import date, datetime

from etf_engine.config.settings import settings
from etf_engine.domain.quality import DataQualityIssue, error, warn
from etf_engine.ingestion.raw_store import RawSnapshotStore
from etf_engine.ingestion.run_recorder import IngestionRunRecorder
from etf_engine.ingestion.source_health import track_source_health
from etf_engine.ingestion.validator import validate_share
from etf_engine.jobs.sync_calendar import ensure_market_calendar
from etf_engine.repositories.nav_repository import NavRepository
from etf_engine.repositories.quality_issue_repository import QualityIssueRepository
from etf_engine.repositories.share_repository import ShareRepository
from etf_engine.sources.registry import registry


def sync_shares(trade_date: date | None = None, backfill_days: int = 1) -> dict:
    """同步 ETF 份额。

    ``backfill_days > 1`` 只对"自带统计日期"的来源生效（当前是上交所）；
    快照类来源（深交所当前份额）永远只写一个日期，避免把同一快照复制成历史。
    """
    repository = ShareRepository()
    nav_repository = NavRepository()
    quality_repository = QualityIssueRepository()
    raw_store = RawSnapshotStore(settings.raw_path)
    recorder = IngestionRunRecorder()
    calendar = ensure_market_calendar()
    # as-of 日期只在这一处解析：快照类来源不允许自己用运行日当交易日。
    asof = trade_date or calendar.latest_closed_trading_day(
        datetime.now().astimezone(),
        data_ready_hour=settings.market_data_ready_hour,
    )

    results: list[dict] = []
    total_written = 0

    for source_cls in registry.share_sources:
        source = source_cls(calendar=calendar)
        source_name = source.source_name
        run_id = recorder.start("etf_share", source_name, asof)
        parse_issues: list[DataQualityIssue] = []
        try:
            backfill = backfill_days > 1 and source.supports_history_backfill
            with track_source_health(source_name, "etf_share"):
                if backfill:
                    shares, parse_issues = source.fetch_shares_history(asof, backfill_days)
                else:
                    shares, parse_issues = source.fetch_shares_with_issues(trade_date=asof)

            snapshot_date = max(item.trade_date for item in shares) if shares else asof
            if shares and getattr(source, "snapshot_date_is_derived", False):
                # 该来源不携带日期，入库日期来自交易日历：必须留痕，避免被当成
                # 上游原生的统计日期。
                parse_issues.append(
                    warn(
                        "share_snapshot_date_derived",
                        f"{source_name} 快照无自带日期，按交易日历记为 "
                        f"{snapshot_date.isoformat() if snapshot_date else 'unknown'}",
                    )
                )

            if shares:
                raw_store.write_records(
                    source=source_name,
                    dataset="etf_share",
                    trade_date=snapshot_date,
                    records=[s.model_dump(mode="json") for s in shares],
                )

            # 份额接口不提供净值时，用独立的净值来源按"同一天"补齐，并单独标注
            # nav_source，不把跨源拼接伪装成单一来源事实，也不用未来净值倒填历史。
            missing_nav_dates = sorted({item.trade_date for item in shares if item.nav is None})
            navs_by_key = nav_repository.navs_for_dates(missing_nav_dates)
            for item in shares:
                if item.nav is not None:
                    continue
                nav = navs_by_key.get((item.security_id, item.trade_date))
                if nav is not None:
                    item.nav = nav
                    item.nav_source = "akshare/eastmoney"

            valid = []
            rejected = 0

            for item in shares:
                item.source_meta.ingestion_run_id = run_id
                validation_issues = validate_share(item)
                if any(issue.is_blocking for issue in validation_issues):
                    rejected += 1
                    quality_repository.record(
                        dataset="etf_share",
                        issues=validation_issues,
                        security_id=item.security_id,
                        trade_date=item.trade_date,
                    )
                    continue
                valid.append(item)

            written = repository.upsert_many(valid)
            total_written += written
            status = "SUCCESS" if rejected == 0 else "PARTIAL"
            recorder.finish(
                run_id,
                status=status,
                rows_fetched=len(shares),
                rows_written=written,
                rows_rejected=rejected,
            )
            issues_written = quality_repository.record(
                dataset="etf_share",
                issues=parse_issues,
                trade_date=snapshot_date,
            )
            results.append(
                {
                    "source": source_name,
                    "run_id": run_id,
                    "asof_date": snapshot_date.isoformat() if snapshot_date else None,
                    "backfill_days": backfill_days if backfill else 1,
                    "rows_fetched": len(shares),
                    "rows_written": written,
                    "rows_rejected": rejected,
                    "quality_issues": issues_written,
                }
            )
        except Exception as exc:
            recorder.finish(
                run_id,
                status="FAILED",
                rows_fetched=0,
                rows_written=0,
                rows_rejected=0,
                error_message=str(exc),
            )
            quality_repository.record(
                dataset="etf_share",
                issues=[error("source_fetch_failed", f"{source_name}: {exc}")],
                trade_date=asof,
            )
            results.append(
                {
                    "source": source_name,
                    "run_id": run_id,
                    "asof_date": asof.isoformat(),
                    "status": "FAILED",
                    "error": str(exc),
                }
            )

    return {"asof_date": asof.isoformat(), "sources": results, "rows_written": total_written}
