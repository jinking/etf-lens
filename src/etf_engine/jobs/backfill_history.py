from datetime import datetime

from etf_engine.domain.identifiers import SecurityId
from etf_engine.ingestion.run_recorder import IngestionRunRecorder
from etf_engine.jobs.sync_calendar import ensure_market_calendar
from etf_engine.repositories.quote_repository import QuoteRepository
from etf_engine.sources.registry import registry


def backfill_history(
    security_ids: list[str] | None = None,
    days: int = 90,
    top_n: int | None = 20,
) -> dict:
    """批量回补 ETF 历史日线数据。

    如果未指定 security_ids，则默认选取本地最新成交额最高的 top_n 只 ETF。
    """
    repository = QuoteRepository()
    source = registry.history_source()
    recorder = IngestionRunRecorder()
    calendar = ensure_market_calendar()

    # 确定目标 ETF 列表
    targets: list[str] = []
    if security_ids:
        for item in security_ids:
            try:
                targets.append(SecurityId.parse(item).value)
            except ValueError:
                continue
    else:
        # 从本地最新行情中按成交额排序挑选
        targets = repository.top_by_turnover(top_n or 20)

    if not targets:
        return {"status": "SKIPPED", "reason": "No target ETFs found"}

    # 历史区间按交易日推进，而不是自然日：days 天自然日会被周末和假期稀释。
    end_date = calendar.latest_closed_trading_day(datetime.now().astimezone())
    window = calendar.trading_days_back(end_date, days)
    start_date = window[-1] if window else end_date
    run_id = recorder.start("etf_history", "akshare_history", None)

    total_fetched = 0
    total_written = 0
    errors: list[str] = []

    for sid in targets:
        try:
            quotes = source.fetch_history(sid, start_date=start_date, end_date=end_date)
            for q in quotes:
                q.source_meta.ingestion_run_id = run_id
            written = repository.upsert_many(quotes)
            total_fetched += len(quotes)
            total_written += written
        except Exception as exc:
            errors.append(f"{sid}: {exc}")

    status = "SUCCESS" if not errors else ("PARTIAL" if total_written > 0 else "FAILED")
    recorder.finish(
        run_id,
        status=status,
        rows_fetched=total_fetched,
        rows_written=total_written,
        rows_rejected=0,
        error_message="; ".join(errors) if errors else None,
    )

    return {
        "run_id": run_id,
        "target_count": len(targets),
        "rows_fetched": total_fetched,
        "rows_written": total_written,
        "errors": errors,
    }
