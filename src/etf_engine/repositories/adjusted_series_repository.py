from datetime import datetime

from etf_engine.config.settings import settings
from etf_engine.db.connection import connect
from etf_engine.domain.models import AdjustedDailyPoint
from etf_engine.research.adjustment import ADJUSTMENT_VERSION


class AdjustedSeriesRepository:
    def upsert_many(self, points: list[AdjustedDailyPoint], con=None) -> int:
        if not points:
            return 0
        calculated_at = datetime.now().astimezone()
        rows = [
            (
                point.security_id,
                point.trade_date,
                float(point.adjusted_close) if point.adjusted_close is not None else None,
                float(point.adjusted_nav) if point.adjusted_nav is not None else None,
                float(point.adjusted_shares) if point.adjusted_shares is not None else None,
                float(point.adjustment_factor),
                float(point.price_adjustment_factor)
                if point.price_adjustment_factor is not None
                else None,
                float(point.nav_adjustment_factor)
                if point.nav_adjustment_factor is not None
                else None,
                float(point.share_adjustment_factor)
                if point.share_adjustment_factor is not None
                else None,
                ADJUSTMENT_VERSION,
                calculated_at,
            )
            for point in points
        ]
        sql = """
        INSERT INTO mart.etf_adjusted_daily (
            security_id, trade_date, adjusted_close, adjusted_nav, adjusted_shares,
            adjustment_factor, price_adjustment_factor, nav_adjustment_factor,
            share_adjustment_factor, calculation_version, calculated_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT (security_id, trade_date, calculation_version) DO UPDATE SET
            adjusted_close = EXCLUDED.adjusted_close,
            adjusted_nav = EXCLUDED.adjusted_nav,
            adjusted_shares = EXCLUDED.adjusted_shares,
            adjustment_factor = EXCLUDED.adjustment_factor,
            price_adjustment_factor = EXCLUDED.price_adjustment_factor,
            nav_adjustment_factor = EXCLUDED.nav_adjustment_factor,
            share_adjustment_factor = EXCLUDED.share_adjustment_factor,
            calculated_at = EXCLUDED.calculated_at
        """
        if con is not None:
            con.executemany(sql, rows)
        else:
            with connect(settings.database_path) as c:
                c.executemany(sql, rows)
        return len(rows)

    def series(self, security_id: str, *, asof_date=None) -> list[dict]:
        with connect(settings.database_path) as con:
            rows = con.execute(
                """
                SELECT * FROM mart.etf_adjusted_daily
                WHERE security_id = ?
                  AND (? IS NULL OR trade_date <= ?)
                ORDER BY trade_date
                """,
                [security_id, asof_date, asof_date],
            ).fetchall()
            columns = [c[0] for c in con.description]
        return [dict(zip(columns, row, strict=True)) for row in rows]

    def count(self) -> int:
        with connect(settings.database_path) as con:
            return int(con.execute("SELECT count(*) FROM mart.etf_adjusted_daily").fetchone()[0])

    def max_factor_by_security(self) -> dict[str, float]:
        with connect(settings.database_path) as con:
            rows = con.execute(
                """
                SELECT security_id, MAX(adjustment_factor)
                FROM mart.etf_adjusted_daily GROUP BY 1
                """
            ).fetchall()
        return {security_id: factor for security_id, factor in rows}
