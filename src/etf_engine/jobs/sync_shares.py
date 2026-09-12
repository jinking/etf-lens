from datetime import date

from etf_engine.config.settings import settings
from etf_engine.ingestion.raw_store import RawSnapshotStore
from etf_engine.ingestion.run_recorder import IngestionRunRecorder
from etf_engine.ingestion.validator import validate_share
from etf_engine.repositories.share_repository import ShareRepository
from etf_engine.sources.sse.shares import SSEETFShareSource
from etf_engine.sources.szse.shares import SZSEETFShareSource


def sync_shares(trade_date: date | None = None) -> dict:
    repository = ShareRepository()
    raw_store = RawSnapshotStore(settings.raw_path)
    recorder = IngestionRunRecorder()

    sources = [
        ("sse", SSEETFShareSource()),
        ("szse", SZSEETFShareSource()),
    ]

    results = []

    for source_name, source in sources:
        run_id = recorder.start("etf_share", source_name, trade_date)
        try:
            shares = source.fetch_shares(trade_date=trade_date)

            if shares:
                snapshot_date = shares[0].trade_date
                raw_store.write_records(
                    source=source_name,
                    dataset="etf_share",
                    trade_date=snapshot_date,
                    records=[s.model_dump(mode="json") for s in shares],
                )

            valid = []
            rejected = 0

            for item in shares:
                item.source_meta.ingestion_run_id = run_id
                issues = validate_share(item)
                if any(issue.severity == "ERROR" for issue in issues):
                    rejected += 1
                    continue
                valid.append(item)

            written = repository.upsert_many(valid)
            status = "SUCCESS" if rejected == 0 else "PARTIAL"
            recorder.finish(
                run_id,
                status=status,
                rows_fetched=len(shares),
                rows_written=written,
                rows_rejected=rejected,
            )
            results.append(
                {
                    "source": source_name,
                    "run_id": run_id,
                    "rows_fetched": len(shares),
                    "rows_written": written,
                    "rows_rejected": rejected,
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
            results.append(
                {
                    "source": source_name,
                    "run_id": run_id,
                    "status": "FAILED",
                    "error": str(exc),
                }
            )

    return {"sources": results}
