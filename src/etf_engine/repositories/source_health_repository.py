from datetime import datetime

from etf_engine.config.settings import settings
from etf_engine.db.connection import connect


class SourceHealthRepository:
    """``ops.source_health`` 的读写入口。

    记录每个 (source, capability) 的最近成败与连续失败次数，
    用于回答"哪个数据源最近不稳"。
    """

    def record_success(self, source: str, capability: str) -> None:
        now = datetime.now().astimezone()
        with connect(settings.database_path) as con:
            con.execute(
                """
                INSERT INTO ops.source_health (
                    source, capability, status, last_success_at, consecutive_failures
                ) VALUES (?, ?, 'OK', ?, 0)
                ON CONFLICT (source, capability) DO UPDATE SET
                    status = 'OK',
                    last_success_at = EXCLUDED.last_success_at,
                    consecutive_failures = 0,
                    last_error = NULL
                """,
                [source, capability, now],
            )

    def record_failure(self, source: str, capability: str, error_message: str) -> None:
        now = datetime.now().astimezone()
        with connect(settings.database_path) as con:
            con.execute(
                """
                INSERT INTO ops.source_health (
                    source, capability, status, last_failure_at,
                    consecutive_failures, last_error
                ) VALUES (?, ?, 'FAILED', ?, 1, ?)
                ON CONFLICT (source, capability) DO UPDATE SET
                    status = 'FAILED',
                    last_failure_at = EXCLUDED.last_failure_at,
                    consecutive_failures = ops.source_health.consecutive_failures + 1,
                    last_error = EXCLUDED.last_error
                """,
                [source, capability, now, error_message[:500]],
            )
