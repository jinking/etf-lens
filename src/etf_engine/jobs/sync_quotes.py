from datetime import date

from etf_engine.config.settings import settings
from etf_engine.ingestion.raw_store import RawSnapshotStore
from etf_engine.ingestion.run_recorder import IngestionRunRecorder
from etf_engine.ingestion.validator import validate_quote
from etf_engine.repositories.quote_repository import QuoteRepository
from etf_engine.sources.akshare.quotes import AkshareETFQuoteSource


def sync_quotes(trade_date: date | None = None) -> dict:
    source = AkshareETFQuoteSource()
    repository = QuoteRepository()
    raw_store = RawSnapshotStore(settings.raw_path)
    recorder = IngestionRunRecorder()

    run_id = recorder.start("etf_quote", "akshare", trade_date)

    try:
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

        for quote in quotes:
            quote.source_meta.ingestion_run_id = run_id
            issues = validate_quote(quote)
            if any(issue.severity == "ERROR" for issue in issues):
                rejected += 1
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
