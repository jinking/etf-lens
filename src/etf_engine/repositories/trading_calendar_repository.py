from datetime import date, datetime

from etf_engine.config.settings import settings
from etf_engine.db.connection import connect
from etf_engine.domain.calendar import MarketCalendar


class TradingCalendarRepository:
    """``core.trading_calendar`` 的读写入口。"""

    def upsert_many(
        self,
        trading_days: list[date],
        *,
        source: str,
        upstream_source: str | None = None,
    ) -> int:
        if not trading_days:
            return 0

        fetched_at = datetime.now().astimezone()
        rows = [(day, source, upstream_source, fetched_at) for day in sorted(set(trading_days))]
        sql = """
        INSERT INTO core.trading_calendar (trade_date, source, upstream_source, fetched_at)
        VALUES (?,?,?,?)
        ON CONFLICT (trade_date) DO UPDATE SET
            source = EXCLUDED.source,
            upstream_source = EXCLUDED.upstream_source,
            fetched_at = EXCLUDED.fetched_at
        """
        with connect(settings.database_path) as con:
            con.executemany(sql, rows)
        return len(rows)

    def load(self) -> MarketCalendar | None:
        """加载完整交易日历；库中还没有日历数据时返回 None。"""
        with connect(settings.database_path) as con:
            rows = con.execute(
                "SELECT trade_date FROM core.trading_calendar ORDER BY trade_date"
            ).fetchall()
        if not rows:
            return None
        return MarketCalendar.from_iterable(row[0] for row in rows)

    def bounds(self) -> tuple[date | None, date | None, int]:
        with connect(settings.database_path) as con:
            row = con.execute(
                "SELECT MIN(trade_date), MAX(trade_date), COUNT(*) FROM core.trading_calendar"
            ).fetchone()
        return (row[0], row[1], row[2]) if row else (None, None, 0)


def require_market_calendar() -> MarketCalendar:
    """取得交易日历；缺失时给出可执行的修复指令。"""
    calendar = TradingCalendarRepository().load()
    if calendar is None:
        raise RuntimeError(
            "本地交易日历为空，先执行 `etf sync-calendar`（或 `etf db-init` 后重新初始化）。"
        )
    return calendar
