from datetime import date

from etf_engine.domain.calendar import MarketCalendar
from etf_engine.ingestion.run_recorder import IngestionRunRecorder
from etf_engine.repositories.trading_calendar_repository import (
    TradingCalendarRepository,
    require_market_calendar,
)
from etf_engine.sources.registry import registry


def sync_calendar(
    start_date: date | None = None,
    end_date: date | None = None,
) -> dict:
    """把权威交易日历同步到 ``core.trading_calendar``。

    所有"今天是不是交易日"的判断都必须来自这里，禁止用 Monday-Friday 近似。
    """
    today = date.today()
    start = start_date or date(today.year - 1, 1, 1)
    end = end_date or date(today.year + 1, 12, 31)

    source = registry.calendar_source()
    repository = TradingCalendarRepository()
    recorder = IngestionRunRecorder()
    run_id = recorder.start("trading_calendar", "akshare", None)

    try:
        trading_days = source.fetch_trading_days(start, end)
        written = repository.upsert_many(
            trading_days, source="akshare", upstream_source=source.upstream_source
        )
        recorder.finish(
            run_id,
            status="SUCCESS",
            rows_fetched=len(trading_days),
            rows_written=written,
            rows_rejected=0,
        )
        return {
            "run_id": run_id,
            "start": start.isoformat(),
            "end": end.isoformat(),
            "rows_fetched": len(trading_days),
            "rows_written": written,
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


def ensure_market_calendar() -> MarketCalendar:
    """确保本地存在覆盖今天的交易日历。

    已存在但未覆盖今天时先尝试刷新；刷新失败仍回退到已有日历，
    避免上游抖动让整条数据链路停摆。
    """
    repository = TradingCalendarRepository()
    calendar = repository.load()
    today = date.today()
    if calendar is not None and calendar.last_day >= today:
        return calendar
    try:
        sync_calendar()
    except Exception:
        if calendar is not None:
            return calendar
        raise
    return require_market_calendar()
