from datetime import date

from etf_engine.config.settings import settings
from etf_engine.db.connection import connect
from etf_engine.domain.models import ETFCorporateAction


class CorporateActionRepository:
    def upsert_many(self, actions: list[ETFCorporateAction]) -> int:
        if not actions:
            return 0
        rows = [
            (
                action.security_id,
                action.action_date,
                action.action_type.value,
                action.split_ratio,
                float(action.nav_adjustment_factor)
                if action.nav_adjustment_factor is not None
                else None,
                float(action.share_adjustment_factor)
                if action.share_adjustment_factor is not None
                else None,
                float(action.cash_distribution) if action.cash_distribution is not None else None,
                action.source_meta.source,
                action.source_meta.upstream_source,
                action.source_meta.fetched_at,
                action.source_meta.quality_status.value,
                action.source_meta.ingestion_run_id,
            )
            for action in actions
        ]
        sql = """
        INSERT INTO core.etf_corporate_action (
            security_id, action_date, action_type, split_ratio,
            nav_adjustment_factor, share_adjustment_factor, cash_distribution,
            source, upstream_source, fetched_at, quality_status, ingestion_run_id
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT (security_id, action_date, action_type) DO UPDATE SET
            split_ratio = COALESCE(EXCLUDED.split_ratio, core.etf_corporate_action.split_ratio),
            nav_adjustment_factor = COALESCE(
                EXCLUDED.nav_adjustment_factor, core.etf_corporate_action.nav_adjustment_factor
            ),
            share_adjustment_factor = COALESCE(
                EXCLUDED.share_adjustment_factor,
                core.etf_corporate_action.share_adjustment_factor
            ),
            cash_distribution = COALESCE(
                EXCLUDED.cash_distribution, core.etf_corporate_action.cash_distribution
            ),
            source = EXCLUDED.source,
            upstream_source = COALESCE(
                EXCLUDED.upstream_source, core.etf_corporate_action.upstream_source
            ),
            fetched_at = EXCLUDED.fetched_at,
            quality_status = EXCLUDED.quality_status,
            ingestion_run_id = COALESCE(
                EXCLUDED.ingestion_run_id, core.etf_corporate_action.ingestion_run_id
            )
        """
        with connect(settings.database_path) as con:
            con.executemany(sql, rows)
        return len(rows)

    def actions_for(self, security_id: str, asof_date: date | None = None) -> list[dict]:
        """按日期升序返回该公司行为的完整事实（含调整因子）。"""
        with connect(settings.database_path) as con:
            rows = con.execute(
                """
                SELECT * FROM core.etf_corporate_action
                WHERE security_id = ?
                  AND (? IS NULL OR action_date <= ?)
                ORDER BY action_date
                """,
                [security_id, asof_date, asof_date],
            ).fetchall()
            columns = [c[0] for c in con.description]
        return [dict(zip(columns, row, strict=True)) for row in rows]

    def count(self) -> int:
        with connect(settings.database_path) as con:
            return int(con.execute("SELECT count(*) FROM core.etf_corporate_action").fetchone()[0])
