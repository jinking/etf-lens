"""指数链路：目录 → ETF→指数映射 → 成分 → 指数行情。

顺序有依赖：映射依赖目录，成分与行情依赖映射结果。逐只基金取基准文本
（``fund_info_ths``）与逐只指数取成分都是按标的请求，因此都做成有界限速任务。
"""

import time
from datetime import date, datetime
from functools import partial

from etf_engine.config.settings import settings
from etf_engine.db.connection import connect
from etf_engine.domain.identifiers import SecurityId
from etf_engine.domain.quality import DataQualityIssue, error, warn
from etf_engine.ingestion.index_matcher import match_index
from etf_engine.ingestion.retry import with_retry
from etf_engine.ingestion.run_recorder import IngestionRunRecorder
from etf_engine.ingestion.source_health import track_source_health
from etf_engine.jobs.sync_calendar import ensure_market_calendar
from etf_engine.repositories.index_repository import IndexRepository
from etf_engine.repositories.quality_issue_repository import QualityIssueRepository
from etf_engine.sources.registry import registry

DEFAULT_SLEEP_SECONDS = 0.3
#: 指数行情回溯的交易日数量，60 日跟踪误差需要足够窗口。
DEFAULT_QUOTE_TRADING_DAYS = 90


def sync_index_catalog() -> dict:
    """同步指数目录（中证全量清单 + 新浪行情符号）。"""
    source = registry.index_catalog_source()
    repository = IndexRepository()
    quality = QualityIssueRepository()
    recorder = IngestionRunRecorder()
    run_id = recorder.start("index_catalog", "csindex", None)

    try:
        with track_source_health("csindex", "index_catalog"):
            entries, issues = source.fetch_catalog()
        written = repository.upsert_catalog(entries)
        issues_written = quality.record(dataset="index_catalog", issues=issues)
        recorder.finish(
            run_id,
            status="SUCCESS",
            rows_fetched=len(entries),
            rows_written=written,
            rows_rejected=0,
        )
        return {
            "run_id": run_id,
            "status": "SUCCESS",
            "rows_written": written,
            "with_market_symbol": sum(1 for e in entries if e.market_symbol),
            "quality_issues": issues_written,
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


def _map_targets(security_ids: list[str] | None, limit: int | None) -> list[str]:
    if security_ids:
        targets: list[str] = []
        for item in security_ids:
            try:
                targets.append(SecurityId.parse(item).value)
            except ValueError:
                continue
        return targets

    sql = """
    WITH latest AS (
        SELECT security_id, estimated_aum,
               ROW_NUMBER() OVER (PARTITION BY security_id ORDER BY trade_date DESC) AS rn
        FROM core.etf_share_daily
    )
    SELECT m.security_id
    FROM core.etf_master m
    LEFT JOIN latest s ON s.security_id = m.security_id AND s.rn = 1
    WHERE m.tracking_index_id IS NULL
    ORDER BY s.estimated_aum DESC NULLS LAST, m.security_id
    """
    values: list = []
    if limit is not None:
        sql += " LIMIT ?"
        values.append(limit)
    with connect(settings.database_path) as con:
        return [row[0] for row in con.execute(sql, values).fetchall()]


def sync_index_map(
    security_ids: list[str] | None = None,
    limit: int | None = 50,
    sleep_seconds: float = DEFAULT_SLEEP_SECONDS,
    benchmark_lookup=None,
) -> dict:
    """按基金"业绩比较基准"对齐跟踪指数。

    匹配不唯一或匹配不到时只记问题，不写映射——指数映射是事实，不允许猜。
    """
    repository = IndexRepository()
    quality = QualityIssueRepository()
    recorder = IngestionRunRecorder()
    catalog = repository.catalog()
    if not catalog:
        return {"status": "SKIPPED", "reason": "指数目录为空，先执行 etf sync-index-catalog"}

    lookup = benchmark_lookup or registry.index_benchmark_source().fetch_benchmark
    targets = _map_targets(security_ids, limit)
    if not targets:
        return {"status": "SKIPPED", "reason": "没有需要映射跟踪指数的 ETF"}

    name_catalog = {index_id: [entry["index_name"]] for index_id, entry in catalog.items()}
    run_id = recorder.start("etf_index_map", "fund_benchmark", None)
    records: list[dict] = []
    unnamed: list[tuple[str, str]] = []
    issues: list[DataQualityIssue] = []
    failures = 0

    for security_id in targets:
        try:
            with track_source_health("ths", "etf_benchmark"):
                benchmark = with_retry(partial(lookup, security_id))
        except Exception as exc:
            failures += 1
            issues.append(error("benchmark_fetch_failed", f"{security_id}: {exc}"))
            continue

        if not benchmark:
            issues.append(warn("benchmark_unavailable", security_id))
            continue

        matched = match_index(benchmark, name_catalog)
        if matched is None:
            # 代码没对齐，但"跟踪标的名"是基金披露的事实，仍然保留下来。
            unnamed.append((security_id, benchmark))
            issues.append(warn("index_match_failed", f"{security_id} 业绩比较基准={benchmark!r}"))
            continue

        records.append(
            {
                "etf_id": security_id,
                "index_id": matched.index_id,
                "index_name": matched.index_name,
                # valid_from 记录的是"我们观测到该跟踪关系"的日期：基准文本是
                # 当前事实，历史起点未知，不用推断值冒充历史。
                "valid_from": date.today(),
                "source": "fund_benchmark",
            }
        )
        if sleep_seconds:
            time.sleep(sleep_seconds)

    written = repository.upsert_map(records)
    repository.set_master_index_name(unnamed)
    issues_written = quality.record(dataset="etf_index_map", issues=issues)
    status = "SUCCESS" if failures == 0 else ("PARTIAL" if records else "FAILED")
    recorder.finish(
        run_id,
        status=status,
        rows_fetched=len(targets),
        rows_written=written,
        rows_rejected=failures,
    )
    return {
        "run_id": run_id,
        "status": status,
        "target_count": len(targets),
        "rows_written": written,
        "unmatched": len(targets) - len(records) - failures,
        "failures": failures,
        "quality_issues": issues_written,
    }


def sync_index_details(
    limit_indices: int | None = None,
    quote_trading_days: int = DEFAULT_QUOTE_TRADING_DAYS,
) -> dict:
    """同步跟踪指数的成分与行情。"""
    repository = IndexRepository()
    quality = QualityIssueRepository()
    recorder = IngestionRunRecorder()
    calendar = ensure_market_calendar()

    targets = repository.tracked_indices(limit=limit_indices)
    if not targets:
        return {"status": "SKIPPED", "reason": "还没有 ETF→指数映射，先执行 etf sync-index-map"}

    constituent_source = registry.index_constituent_source()
    quote_source = registry.index_quote_source()
    end_date = calendar.latest_closed_trading_day(datetime.now().astimezone())
    window = calendar.trading_days_back(end_date, quote_trading_days)
    start_date = window[-1] if window else end_date
    existing_quotes = repository.index_ids_with_quotes(start_date, end_date)

    run_id = recorder.start("index_details", "csindex_sina", end_date)
    total_constituents = 0
    total_quotes = 0
    issues: list[DataQualityIssue] = []

    for index_id, market_symbol in targets:
        with track_source_health("csindex", "index_constituent"):
            constituents, constituent_issues = constituent_source.fetch_constituents_with_issues(
                index_id
            )
        total_constituents += repository.upsert_constituents(constituents)
        issues.extend(constituent_issues)

        if index_id in existing_quotes:
            # 已经有窗口内的行情，不重复拉取。
            continue

        with track_source_health("index_quote", "index_quote"):
            quotes, quote_issues = quote_source.fetch_quotes(
                index_id, market_symbol, start_date=start_date, end_date=end_date
            )
        total_quotes += repository.upsert_quotes(quotes)
        issues.extend(quote_issues)

    issues_written = quality.record(dataset="index_details", issues=issues, trade_date=end_date)
    recorder.finish(
        run_id,
        status="SUCCESS" if not issues else "PARTIAL",
        rows_fetched=len(targets),
        rows_written=total_constituents + total_quotes,
        rows_rejected=0,
    )
    return {
        "run_id": run_id,
        "status": "SUCCESS" if not issues else "PARTIAL",
        "index_count": len(targets),
        "constituents_written": total_constituents,
        "quotes_written": total_quotes,
        "quality_issues": issues_written,
    }
