"""宽基指数长历史回补（位置分位用）。

指数日线没有"全市场一次拉完"的问题，但**长历史**必须专门回补：
日常同步只取 90 个交易日，算不出 250 日分位，更算不出 3 年分位。

只回补 ``core.index_catalog`` 里有行情符号的指数——符号是数据源事实，
没有符号就如实记问题，不按代码规则猜符号。
"""

import time
from datetime import date, timedelta

from etf_engine.domain.quality import DataQualityIssue, warn
from etf_engine.ingestion.run_recorder import IngestionRunRecorder
from etf_engine.ingestion.source_health import track_source_health
from etf_engine.repositories.index_repository import IndexRepository
from etf_engine.repositories.quality_issue_repository import QualityIssueRepository
from etf_engine.research.market_pulse import broad_index_ids
from etf_engine.sources.registry import registry

#: 默认回补年数。3 年分位需要至少 3 年日线，取 6 年留出余量。
DEFAULT_HISTORY_YEARS = 6
DEFAULT_SLEEP_SECONDS = 0.3

#: 除了宽基篮子，再补一条代表 A 股整体的指数（位置与量价象限参照）。
EXTRA_INDEX_IDS = ("000001",)


def backfill_index_history(
    index_ids: list[str] | None = None,
    years: int = DEFAULT_HISTORY_YEARS,
    sleep_seconds: float = DEFAULT_SLEEP_SECONDS,
) -> dict:
    repository = IndexRepository()
    quality_repository = QualityIssueRepository()
    recorder = IngestionRunRecorder()

    targets = index_ids or [*broad_index_ids(), *EXTRA_INDEX_IDS]
    catalog = repository.catalog()
    end = date.today()
    start = end - timedelta(days=int(365.25 * years))

    run_id = recorder.start("index_history", "sina+csindex", end)
    written = 0
    issues: list[DataQualityIssue] = []
    per_index: dict[str, int] = {}

    try:
        for index_id in targets:
            symbol = (catalog.get(index_id) or {}).get("market_symbol")
            if not symbol:
                issues.append(
                    warn(
                        "index_quote_source_missing",
                        f"{index_id} 在指数目录里没有行情符号，无法回补历史",
                    )
                )
                per_index[index_id] = 0
                continue
            try:
                with track_source_health("sina", "index_history"):
                    quotes, source_issues = registry.index_quote_source().fetch_quotes(
                        index_id, symbol, start, end
                    )
            except Exception as exc:
                issues.append(warn("index_history_fetch_failed", f"{index_id}: {exc}"))
                per_index[index_id] = 0
                continue
            issues.extend(source_issues)
            written += repository.upsert_quotes(quotes)
            per_index[index_id] = len(quotes)
            time.sleep(sleep_seconds)

        issues_written = quality_repository.record(dataset="index_history", issues=issues)
        recorder.finish(
            run_id,
            status="SUCCESS" if written else "PARTIAL",
            rows_fetched=sum(per_index.values()),
            rows_written=written,
            rows_rejected=0,
        )
        return {
            "run_id": run_id,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "per_index": per_index,
            "rows_written": written,
            "quality_issues": issues_written,
        }
    except Exception as exc:
        recorder.finish(
            run_id,
            status="FAILED",
            rows_fetched=0,
            rows_written=written,
            rows_rejected=0,
            error_message=str(exc),
        )
        raise
