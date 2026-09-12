from datetime import date, datetime
from uuid import uuid4

from etf_engine.config.settings import settings
from etf_engine.db.connection import connect


class IngestionRunRecorder:
    def start(self, dataset: str, source: str, trade_date: date | None) -> str:
        run_id = uuid4().hex
        with connect(settings.database_path) as con:
            con.execute(
                """
                INSERT INTO ops.ingestion_run(
                    run_id, dataset, source, trade_date, started_at, status
                ) VALUES (?, ?, ?, ?, ?, 'RUNNING')
                """,
                [run_id, dataset, source, trade_date, datetime.now().astimezone()],
            )
        return run_id

    def finish(
        self,
        run_id: str,
        *,
        status: str,
        rows_fetched: int,
        rows_written: int,
        rows_rejected: int,
        error_message: str | None = None,
    ) -> None:
        with connect(settings.database_path) as con:
            con.execute(
                """
                UPDATE ops.ingestion_run
                SET finished_at = ?,
                    status = ?,
                    rows_fetched = ?,
                    rows_written = ?,
                    rows_rejected = ?,
                    error_message = ?
                WHERE run_id = ?
                """,
                [
                    datetime.now().astimezone(),
                    status,
                    rows_fetched,
                    rows_written,
                    rows_rejected,
                    error_message,
                    run_id,
                ],
            )
