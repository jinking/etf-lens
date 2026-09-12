from datetime import datetime

from etf_engine.config.settings import settings
from etf_engine.ingestion.raw_store import RawSnapshotStore
from etf_engine.ingestion.run_recorder import IngestionRunRecorder
from etf_engine.repositories.master_repository import MasterRepository
from etf_engine.sources.master import UnifiedETFMasterSource


def sync_master() -> dict:
    source = UnifiedETFMasterSource()
    repository = MasterRepository()
    raw_store = RawSnapshotStore(settings.raw_path)
    recorder = IngestionRunRecorder()

    run_id = recorder.start("etf_master", "unified_master", None)

    try:
        masters = source.fetch_masters()
        today = datetime.now().date()

        if masters:
            raw_store.write_records(
                source="unified",
                dataset="etf_master",
                trade_date=today,
                records=[m.model_dump(mode="json") for m in masters],
            )

        for m in masters:
            m.source_meta.ingestion_run_id = run_id

        written = repository.upsert_many(masters)
        recorder.finish(
            run_id,
            status="SUCCESS",
            rows_fetched=len(masters),
            rows_written=written,
            rows_rejected=0,
        )

        return {
            "run_id": run_id,
            "rows_fetched": len(masters),
            "rows_written": written,
            "rows_rejected": 0,
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
