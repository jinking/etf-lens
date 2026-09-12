from etf_engine.config.settings import settings
from etf_engine.db.connection import connect
from etf_engine.domain.models import ETFShare


class ShareRepository:
    def upsert_many(self, shares: list[ETFShare]) -> int:
        if not shares:
            return 0

        rows = []
        for s in shares:
            estimated_aum = None
            if s.nav is not None:
                # 估算规模 = 份额 × 单位净值，属于派生值，必须带 is_estimated 标记。
                estimated_aum = float(s.shares * s.nav)

            rows.append(
                (
                    s.security_id,
                    s.trade_date,
                    s.fund_name,
                    s.shares,
                    s.nav,
                    s.nav_source,
                    estimated_aum,
                    estimated_aum is not None,
                    s.source_meta.source,
                    s.source_meta.upstream_source,
                    s.source_meta.fetched_at,
                    s.source_meta.quality_status.value,
                    s.source_meta.ingestion_run_id,
                )
            )

        sql = """
        INSERT INTO core.etf_share_daily (
            security_id, trade_date, fund_name, shares, nav, nav_source,
            estimated_aum, is_estimated_aum,
            source, upstream_source, fetched_at, quality_status, ingestion_run_id
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT (security_id, trade_date) DO UPDATE SET
            fund_name = EXCLUDED.fund_name,
            shares = EXCLUDED.shares,
            nav = COALESCE(EXCLUDED.nav, core.etf_share_daily.nav),
            nav_source = COALESCE(EXCLUDED.nav_source, core.etf_share_daily.nav_source),
            estimated_aum = COALESCE(EXCLUDED.estimated_aum, core.etf_share_daily.estimated_aum),
            is_estimated_aum = EXCLUDED.is_estimated_aum,
            source = EXCLUDED.source,
            upstream_source = EXCLUDED.upstream_source,
            fetched_at = EXCLUDED.fetched_at,
            quality_status = EXCLUDED.quality_status,
            ingestion_run_id = EXCLUDED.ingestion_run_id
        """

        with connect(settings.database_path) as con:
            con.executemany(sql, rows)
        return len(rows)
