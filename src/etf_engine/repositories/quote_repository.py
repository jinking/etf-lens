from etf_engine.config.settings import settings
from etf_engine.db.connection import connect
from etf_engine.domain.models import ETFQuote


class QuoteRepository:
    def upsert_many(self, quotes: list[ETFQuote]) -> int:
        if not quotes:
            return 0

        rows = []
        for q in quotes:
            rows.append(
                (
                    q.security_id,
                    q.trade_date,
                    q.name,
                    q.open,
                    q.high,
                    q.low,
                    q.close,
                    q.prev_close,
                    q.change,
                    q.change_pct,
                    q.volume,
                    q.turnover_amount,
                    q.turnover_rate,
                    q.amplitude,
                    q.iopv,
                    q.premium_discount_pct,
                    q.premium_discount_pct_normalized,
                    q.bid1,
                    q.ask1,
                    q.bid1_volume,
                    q.ask1_volume,
                    q.trading_flow_main,
                    q.trading_flow_super_large,
                    q.trading_flow_large,
                    q.trading_flow_medium,
                    q.trading_flow_small,
                    q.source_meta.source,
                    q.source_meta.upstream_source,
                    q.source_meta.fetched_at,
                    q.source_meta.quality_status.value,
                    q.source_meta.ingestion_run_id,
                )
            )

        sql = """
        INSERT INTO core.etf_quote_daily (
            security_id, trade_date, name, open, high, low, close, prev_close,
            change, change_pct, volume, turnover_amount, turnover_rate, amplitude,
            iopv, premium_discount_pct, premium_discount_pct_normalized, bid1, ask1,
            bid1_volume, ask1_volume, trading_flow_main, trading_flow_super_large,
            trading_flow_large, trading_flow_medium, trading_flow_small, source,
            upstream_source, fetched_at, quality_status, ingestion_run_id
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT (security_id, trade_date) DO UPDATE SET
            name = EXCLUDED.name,
            open = EXCLUDED.open,
            high = EXCLUDED.high,
            low = EXCLUDED.low,
            close = EXCLUDED.close,
            prev_close = EXCLUDED.prev_close,
            change = EXCLUDED.change,
            change_pct = EXCLUDED.change_pct,
            volume = EXCLUDED.volume,
            turnover_amount = EXCLUDED.turnover_amount,
            turnover_rate = EXCLUDED.turnover_rate,
            amplitude = EXCLUDED.amplitude,
            iopv = EXCLUDED.iopv,
            premium_discount_pct = EXCLUDED.premium_discount_pct,
            premium_discount_pct_normalized = EXCLUDED.premium_discount_pct_normalized,
            bid1 = EXCLUDED.bid1,
            ask1 = EXCLUDED.ask1,
            bid1_volume = EXCLUDED.bid1_volume,
            ask1_volume = EXCLUDED.ask1_volume,
            trading_flow_main = EXCLUDED.trading_flow_main,
            trading_flow_super_large = EXCLUDED.trading_flow_super_large,
            trading_flow_large = EXCLUDED.trading_flow_large,
            trading_flow_medium = EXCLUDED.trading_flow_medium,
            trading_flow_small = EXCLUDED.trading_flow_small,
            source = EXCLUDED.source,
            upstream_source = EXCLUDED.upstream_source,
            fetched_at = EXCLUDED.fetched_at,
            quality_status = EXCLUDED.quality_status,
            ingestion_run_id = EXCLUDED.ingestion_run_id
        """

        with connect(settings.database_path) as con:
            con.executemany(sql, rows)
        return len(rows)

    def get_latest(self, security_id: str) -> dict | None:
        with connect(settings.database_path) as con:
            row = con.execute(
                """
                SELECT *
                FROM core.etf_quote_daily
                WHERE security_id = ?
                ORDER BY trade_date DESC
                LIMIT 1
                """,
                [security_id],
            ).fetchone()
            if row is None:
                return None
            columns = [d[0] for d in con.description]
            return dict(zip(columns, row, strict=True))

    def search_latest(self, query: str | None = None, limit: int = 20) -> list[dict]:
        """Return the latest locally stored quote for each matching ETF."""
        filters = "WHERE row_number = 1"
        values: list[str | int] = []
        if query:
            filters += " AND (security_id ILIKE ? OR name ILIKE ?)"
            pattern = f"%{query}%"
            values.extend([pattern, pattern])
        values.append(limit)

        with connect(settings.database_path) as con:
            rows = con.execute(
                f"""
                SELECT * EXCLUDE (row_number)
                FROM (
                    SELECT *, ROW_NUMBER() OVER (
                        PARTITION BY security_id ORDER BY trade_date DESC
                    ) AS row_number
                    FROM core.etf_quote_daily
                )
                {filters}
                ORDER BY turnover_amount DESC NULLS LAST, security_id
                LIMIT ?
                """,
                values,
            ).fetchall()
            columns = [description[0] for description in con.description]
            return [dict(zip(columns, row, strict=True)) for row in rows]

    def dashboard_summary(self) -> dict:
        """Return truthful dashboard metadata derived only from local quotes."""
        with connect(settings.database_path) as con:
            row = con.execute(
                """
                WITH latest_quotes AS (
                    SELECT * EXCLUDE (row_number)
                    FROM (
                        SELECT *, ROW_NUMBER() OVER (
                            PARTITION BY security_id ORDER BY trade_date DESC
                        ) AS row_number
                        FROM core.etf_quote_daily
                    )
                    WHERE row_number = 1
                )
                SELECT
                    COUNT(*) AS etf_count,
                    MAX(trade_date) AS latest_trade_date,
                    SUM(turnover_amount) AS total_turnover_amount
                FROM latest_quotes
                """
            ).fetchone()
        return {
            "etf_count": row[0],
            "latest_trade_date": row[1],
            "total_turnover_amount": row[2],
        }
