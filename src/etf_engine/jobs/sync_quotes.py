from datetime import date

from etf_engine.config.settings import settings
from etf_engine.domain.quality import error
from etf_engine.ingestion.raw_store import RawSnapshotStore
from etf_engine.ingestion.run_recorder import IngestionRunRecorder
from etf_engine.ingestion.source_health import track_source_health
from etf_engine.ingestion.validator import validate_quote
from etf_engine.jobs.sync_calendar import ensure_market_calendar
from etf_engine.repositories.quality_issue_repository import QualityIssueRepository
from etf_engine.repositories.quote_repository import QuoteRepository
from etf_engine.sources.registry import registry


def sync_quotes(trade_date: date | None = None) -> dict:
    source = registry.quote_source()
    repository = QuoteRepository()
    quality_repository = QualityIssueRepository()
    raw_store = RawSnapshotStore(settings.raw_path)
    recorder = IngestionRunRecorder()
    calendar = ensure_market_calendar()

    run_id = recorder.start("etf_quote", "akshare", trade_date)

    try:
        with track_source_health("akshare/eastmoney", "etf_quote"):
            quotes = source.fetch_quotes(trade_date=trade_date)

        if quotes:
            snapshot_date = quotes[0].trade_date
            raw_store.write_records(
                source="akshare",
                dataset="etf_quote",
                trade_date=snapshot_date,
                records=[q.model_dump(mode="json") for q in quotes],
            )

        valid = []
        rejected = 0
        issues_written = 0

        for quote in quotes:
            quote.source_meta.ingestion_run_id = run_id
            issues = validate_quote(quote)
            if calendar.covers(quote.trade_date) and not calendar.is_trading_day(quote.trade_date):
                # 非交易日的行情只可能来自错误的日期推断（历史上深交所份额
                # 就把周六写进过库），一律拦在入库之前。
                issues.append(
                    error(
                        "quote_trade_date_not_trading_day",
                        f"{quote.security_id} trade_date={quote.trade_date.isoformat()} 不是交易日",
                    )
                )
            if any(issue.is_blocking for issue in issues):
                rejected += 1
                issues_written += quality_repository.record(
                    dataset="etf_quote",
                    issues=issues,
                    security_id=quote.security_id,
                    trade_date=quote.trade_date,
                )
                continue
            valid.append(quote)

        written = repository.upsert_many(valid)
        status = "SUCCESS" if rejected == 0 else "PARTIAL"
        recorder.finish(
            run_id,
            status=status,
            rows_fetched=len(quotes),
            rows_written=written,
            rows_rejected=rejected,
        )

        return {
            "run_id": run_id,
            "rows_fetched": len(quotes),
            "rows_written": written,
            "rows_rejected": rejected,
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
        quality_repository.record(
            dataset="etf_quote",
            issues=[error("source_fetch_failed", f"akshare: {exc}")],
            trade_date=trade_date,
        )
        raise
