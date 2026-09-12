from datetime import date
from decimal import Decimal

from etf_engine.config.settings import settings
from etf_engine.db.connection import connect
from etf_engine.domain.models import ETFNav


class NavRepository:
    def upsert_many(self, navs: list[ETFNav]) -> int:
        if not navs:
            return 0

        rows = [
            (
                nav.security_id,
                nav.nav_date,
                nav.unit_nav,
                nav.adjusted_nav,
                nav.source_meta.source,
                nav.source_meta.fetched_at,
                nav.source_meta.quality_status.value,
            )
            for nav in navs
        ]
        sql = """
        INSERT INTO core.etf_nav_daily (
            security_id, nav_date, unit_nav, adjusted_nav, source, fetched_at, quality_status
        ) VALUES (?,?,?,?,?,?,?)
        ON CONFLICT (security_id, nav_date) DO UPDATE SET
            unit_nav = EXCLUDED.unit_nav,
            adjusted_nav = COALESCE(EXCLUDED.adjusted_nav, core.etf_nav_daily.adjusted_nav),
            source = EXCLUDED.source,
            fetched_at = EXCLUDED.fetched_at,
            quality_status = EXCLUDED.quality_status
        """
        with connect(settings.database_path) as con:
            con.executemany(sql, rows)
        return len(rows)

    def navs_for_dates(self, dates: list[date]) -> dict[tuple[str, date], Decimal]:
        """按 (security_id, 日期) 精确匹配净值。

        份额入库时用这个映射补齐净值：只接受同一天的净值，绝不用"未来"的净值
        给历史份额行做估算。DuckDB 的 DOUBLE 回到 Python 是 float，而份额是
        Decimal，在仓储边界统一成 Decimal。
        """
        if not dates:
            return {}

        placeholders = ",".join(["?"] * len(dates))
        with connect(settings.database_path) as con:
            rows = con.execute(
                f"""
                SELECT security_id, nav_date, unit_nav
                FROM core.etf_nav_daily
                WHERE nav_date IN ({placeholders}) AND unit_nav IS NOT NULL
                """,
                list(dates),
            ).fetchall()
        return {
            (security_id, nav_date): Decimal(str(unit_nav))
            for security_id, nav_date, unit_nav in rows
            if unit_nav is not None
        }
