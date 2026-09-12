from datetime import date

from etf_engine.config.settings import settings
from etf_engine.db.connection import connect
from etf_engine.domain.models import ETFHolding


class HoldingRepository:
    def upsert_many(self, holdings: list[ETFHolding]) -> int:
        if not holdings:
            return 0

        rows = []
        for h in holdings:
            rows.append(
                (
                    h.etf_id,
                    h.report_date,
                    h.disclosure_date,
                    h.stock_id,
                    h.stock_name,
                    float(h.weight_pct) if h.weight_pct is not None else None,
                    float(h.shares) if h.shares is not None else None,
                    float(h.market_value) if h.market_value is not None else None,
                    h.source_meta.source,
                    h.source_meta.fetched_at,
                )
            )

        sql = """
        INSERT INTO core.etf_holding_disclosure (
            etf_id, report_date, disclosure_date, stock_id, stock_name,
            weight_pct, shares, market_value, source, fetched_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT (etf_id, report_date, stock_id) DO UPDATE SET
            disclosure_date = EXCLUDED.disclosure_date,
            stock_name = EXCLUDED.stock_name,
            weight_pct = EXCLUDED.weight_pct,
            shares = EXCLUDED.shares,
            market_value = EXCLUDED.market_value,
            source = EXCLUDED.source,
            fetched_at = EXCLUDED.fetched_at
        """

        with connect(settings.database_path) as con:
            con.executemany(sql, rows)
        return len(rows)

    def get_latest_top10(self, etf_id: str) -> tuple[list[dict], date | None]:
        with connect(settings.database_path) as con:
            dates = con.execute(
                "SELECT MAX(report_date) FROM core.etf_holding_disclosure WHERE etf_id = ?",
                [etf_id],
            ).fetchone()
            if not dates or not dates[0]:
                return [], None
            latest_date = dates[0]
            rows = con.execute(
                """
                SELECT stock_id, stock_name, weight_pct, shares, market_value
                FROM core.etf_holding_disclosure
                WHERE etf_id = ? AND report_date = ?
                ORDER BY weight_pct DESC NULLS LAST
                LIMIT 10
                """,
                [etf_id, latest_date],
            ).fetchall()
            cols = [c[0] for c in con.description]
            return [dict(zip(cols, r, strict=True)) for r in rows], latest_date
