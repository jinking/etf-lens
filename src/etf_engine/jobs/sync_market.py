"""看盘台市场层同步：成交额 / 两融 / 估值 / 涨跌家数。

四条链路各有各的口径与频率，因此分别同步、分别记录 run 与来源健康度，
不揉成一个"同步市场数据"的黑盒任务：

* 成交额：交易所每日概况，按交易日逐日，可回补；
* 两融：上游一次给全量历史，按区间切片；
* 估值：上游给低频序列（自带历史分位）；
* 涨跌家数：只有当日快照，自带统计日期，不能按运行日顶替。
"""

import time
from datetime import date, datetime, timedelta
from functools import partial

from etf_engine.config.settings import settings
from etf_engine.domain.quality import DataQualityIssue, error
from etf_engine.ingestion.raw_store import RawSnapshotStore
from etf_engine.ingestion.retry import call_with_deadline, socket_timeout, with_retry
from etf_engine.ingestion.run_recorder import IngestionRunRecorder
from etf_engine.ingestion.source_health import track_source_health
from etf_engine.jobs.sync_calendar import ensure_market_calendar
from etf_engine.repositories.market_repository import MarketRepository
from etf_engine.repositories.quality_issue_repository import QualityIssueRepository
from etf_engine.research.market_pulse import broad_index_ids
from etf_engine.sources.akshare.valuation import ALL_A_INDEX_ID
from etf_engine.sources.registry import registry

#: 成交额回补的默认交易日数量。
#: 120 个交易日足以让"20 日均额 250 日分位"具备最小样本量（20 + 60）。
DEFAULT_TURNOVER_BACKFILL_DAYS = 120
#: AKShare 的交易所接口是裸 requests，不带 timeout：必须自己兜底，
#: 否则单次上游卡住会让整批回补无限期挂起（实测出现过）。
UPSTREAM_TIMEOUT_SECONDS = 20.0
#: 两融接口一次返回全量历史（约 4000 行），给更宽的窗口。
MARGIN_TIMEOUT_SECONDS = 60.0
#: 逐日请求之间的间隔，避免把交易所接口打疼。
DEFAULT_SLEEP_SECONDS = 0.2


def sync_market_turnover(
    trade_date: date | None = None,
    backfill_days: int = 1,
    sleep_seconds: float = DEFAULT_SLEEP_SECONDS,
) -> dict:
    """同步沪深两市每日成交概况。

    同一交易日分别请求沪深两个交易所；只要有一边成功就写库，
    失败的一边记 quality issue（缺失用 NULL，不用另一边顶替）。
    """
    repository = MarketRepository()
    quality_repository = QualityIssueRepository()
    raw_store = RawSnapshotStore(settings.raw_path)
    recorder = IngestionRunRecorder()
    calendar = ensure_market_calendar()

    asof = trade_date or calendar.latest_closed_trading_day(
        datetime.now().astimezone(),
        data_ready_hour=settings.market_data_ready_hour,
    )
    # 新日期优先：上游抖动时先把最有价值的最近行情落库。
    days = [asof] if backfill_days <= 1 else calendar.trading_days_back(asof, backfill_days)

    run_id = recorder.start("market_turnover", "sse+szse", asof)
    fetched = 0
    written = 0
    issues: list[DataQualityIssue] = []

    try:
        for position, day in enumerate(days):
            if position:
                time.sleep(sleep_seconds)
            for source_cls in registry.market_turnover_sources:
                source = source_cls()
                capability = f"market_turnover_{source.source_name}"

                def _fetch_turnover(source=source, day=day):
                    """单日单所的成交额拉取（带硬超时，供重试包装）。"""
                    return call_with_deadline(
                        partial(source.fetch_turnover_with_issues, day),
                        timeout=UPSTREAM_TIMEOUT_SECONDS,
                    )

                try:
                    with track_source_health(source.source_name, capability):
                        # 超时兜底 + 瞬时错误退避：单点抖动只影响该日该交易所。
                        with socket_timeout(UPSTREAM_TIMEOUT_SECONDS):
                            rows, source_issues = with_retry(_fetch_turnover, attempts=2)
                except Exception as exc:
                    # 单点失败只影响该交易所该日，其余交易日继续。
                    issues.append(
                        error(
                            "market_turnover_fetch_failed",
                            f"{source.source_name} {day.isoformat()}: {exc}",
                        )
                    )
                    continue
                fetched += len(rows)
                issues.extend(source_issues)
                for row in rows:
                    row.source_meta.ingestion_run_id = run_id
                written += repository.upsert_turnover(rows, ingestion_run_id=run_id)
                if rows:
                    raw_store.write_records(
                        source=source.source_name,
                        dataset="market_turnover",
                        trade_date=day,
                        records=[row.model_dump(mode="json") for row in rows],
                    )

        issues_written = quality_repository.record(
            dataset="market_turnover", issues=issues, trade_date=asof
        )
        recorder.finish(
            run_id,
            status="SUCCESS" if not any(i.is_blocking for i in issues) else "PARTIAL",
            rows_fetched=fetched,
            rows_written=written,
            rows_rejected=len([i for i in issues if i.is_blocking]),
        )
        return {
            "run_id": run_id,
            "asof_date": asof.isoformat(),
            "trading_days": len(days),
            "rows_fetched": fetched,
            "rows_written": written,
            "quality_issues": issues_written,
        }
    except Exception as exc:
        recorder.finish(
            run_id,
            status="FAILED",
            rows_fetched=fetched,
            rows_written=written,
            rows_rejected=0,
            error_message=str(exc),
        )
        raise


def sync_margin(days: int = 300) -> dict:
    """同步两融余额（沪 / 深分列）。"""
    repository = MarketRepository()
    quality_repository = QualityIssueRepository()
    recorder = IngestionRunRecorder()

    end = date.today()
    # 两融按自然日发布，多取一些自然日确保覆盖到 N 个交易日。
    start = end - timedelta(days=int(days * 1.7) + 30)

    run_id = recorder.start("market_margin", "akshare_margin", end)
    try:
        source = registry.margin_source()
        with track_source_health(source.source_name, "market_margin"):
            with socket_timeout(UPSTREAM_TIMEOUT_SECONDS):
                rows, issues = with_retry(
                    lambda: call_with_deadline(
                        lambda: source.fetch_margin(start, end),
                        timeout=MARGIN_TIMEOUT_SECONDS,
                    ),
                    attempts=2,
                )
        for row in rows:
            row.source_meta.ingestion_run_id = run_id
        written = repository.upsert_margin(rows, ingestion_run_id=run_id)
        issues_written = quality_repository.record(
            dataset="market_margin", issues=issues, trade_date=end
        )
        recorder.finish(
            run_id,
            status="SUCCESS" if rows else "PARTIAL",
            rows_fetched=len(rows),
            rows_written=written,
            rows_rejected=0,
        )
        return {
            "run_id": run_id,
            "start_date": start.isoformat(),
            "end_date": end.isoformat(),
            "rows_written": written,
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
        quality_repository.record(
            dataset="market_margin",
            issues=[error("market_margin_fetch_failed", str(exc))],
            trade_date=end,
        )
        raise


def sync_market_valuation(start_date: date | None = None) -> dict:
    """同步全 A 估值与历史分位（上游自带分位，属于事实）。"""
    repository = MarketRepository()
    quality_repository = QualityIssueRepository()
    recorder = IngestionRunRecorder()

    run_id = recorder.start("market_valuation", "akshare_legu", None)
    try:
        source = registry.valuation_source()
        with track_source_health(source.source_name, "market_valuation"):
            with socket_timeout(UPSTREAM_TIMEOUT_SECONDS):
                rows, issues = with_retry(
                    lambda: call_with_deadline(
                        lambda: source.fetch_valuation(start_date=start_date),
                        timeout=UPSTREAM_TIMEOUT_SECONDS,
                    ),
                    attempts=2,
                )
        for row in rows:
            row.source_meta.ingestion_run_id = run_id
        written = repository.upsert_valuation(rows, ingestion_run_id=run_id)
        issues_written = quality_repository.record(dataset="market_valuation", issues=issues)
        recorder.finish(
            run_id,
            status="SUCCESS" if rows else "PARTIAL",
            rows_fetched=len(rows),
            rows_written=written,
            rows_rejected=0,
        )
        return {
            "run_id": run_id,
            "index_id": ALL_A_INDEX_ID,
            "rows_written": written,
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


def sync_market_activity(trade_date: date | None = None) -> dict:
    """同步涨跌家数与活跃度。

    上游只有当日快照且自带统计日期；统计日期不是交易日时拒绝入库
    （非交易日的数据只可能来自错误的日期推断）。
    """
    repository = MarketRepository()
    quality_repository = QualityIssueRepository()
    recorder = IngestionRunRecorder()
    calendar = ensure_market_calendar()

    run_id = recorder.start("market_activity", "akshare_legu", trade_date)
    try:
        source = registry.market_activity_source()
        with track_source_health(source.source_name, "market_activity"):
            with socket_timeout(UPSTREAM_TIMEOUT_SECONDS):
                rows, issues = with_retry(
                    lambda: call_with_deadline(
                        lambda: source.fetch_activity(trade_date=trade_date),
                        timeout=UPSTREAM_TIMEOUT_SECONDS,
                    ),
                    attempts=2,
                )

        valid = []
        for row in rows:
            row.source_meta.ingestion_run_id = run_id
            if calendar.covers(row.trade_date) and not calendar.is_trading_day(row.trade_date):
                issues.append(
                    error(
                        "activity_trade_date_not_trading_day",
                        f"统计日期 {row.trade_date.isoformat()} 不是交易日",
                    )
                )
                continue
            valid.append(row)

        written = repository.upsert_activity(valid, ingestion_run_id=run_id)
        issues_written = quality_repository.record(
            dataset="market_activity", issues=issues, trade_date=trade_date
        )
        recorder.finish(
            run_id,
            status="SUCCESS" if valid else "PARTIAL",
            rows_fetched=len(rows),
            rows_written=written,
            rows_rejected=len(rows) - len(valid),
        )
        return {
            "run_id": run_id,
            "rows_written": written,
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


def sync_index_valuation(index_ids: list[str] | None = None) -> dict:
    """同步宽基指数估值序列（月度 PE，上游只覆盖部分宽基指数）。

    没有序列的指数（创业板指、科创50）会记 `index_valuation_symbol_missing`，
    不用别的指数顶替。
    """
    repository = MarketRepository()
    quality_repository = QualityIssueRepository()
    recorder = IngestionRunRecorder()
    targets = index_ids or broad_index_ids()

    run_id = recorder.start("index_valuation", "akshare_legu", None)
    try:
        source = registry.index_valuation_source()
        with track_source_health(source.source_name, "index_valuation"):
            rows, issues = with_retry(
                lambda: call_with_deadline(
                    lambda: source.fetch_index_valuations(targets),
                    timeout=MARGIN_TIMEOUT_SECONDS,
                ),
                attempts=2,
            )
        for row in rows:
            row.source_meta.ingestion_run_id = run_id
        written = repository.upsert_index_valuations(rows, ingestion_run_id=run_id)
        issues_written = quality_repository.record(dataset="index_valuation", issues=issues)
        recorder.finish(
            run_id,
            status="SUCCESS" if rows else "PARTIAL",
            rows_fetched=len(rows),
            rows_written=written,
            rows_rejected=0,
        )
        return {
            "run_id": run_id,
            "rows_written": written,
            "covered_indices": sorted({row.index_id for row in rows}),
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


def sync_fund_issuance() -> dict:
    """同步新发基金（成立日期 + 募集份额）。

    上游一次返回全量列表（约 6800 行、将近 7 秒），因此按"全量覆盖式 upsert"
    处理，不逐只请求；募集份额先空后补的行不会被 NULL 覆盖。
    """
    repository = MarketRepository()
    quality_repository = QualityIssueRepository()
    recorder = IngestionRunRecorder()

    run_id = recorder.start("fund_issuance", "akshare_eastmoney", None)
    try:
        source = registry.fund_issuance_source()
        with track_source_health(source.source_name, "fund_issuance"):
            with socket_timeout(MARGIN_TIMEOUT_SECONDS):
                rows, issues = with_retry(
                    lambda: call_with_deadline(
                        source.fetch_issuances,
                        timeout=MARGIN_TIMEOUT_SECONDS,
                    ),
                    attempts=2,
                )
        for row in rows:
            row.source_meta.ingestion_run_id = run_id
        written = repository.upsert_fund_issuances(rows, ingestion_run_id=run_id)
        issues_written = quality_repository.record(dataset="fund_issuance", issues=issues)
        recorder.finish(
            run_id,
            status="SUCCESS" if rows else "PARTIAL",
            rows_fetched=len(rows),
            rows_written=written,
            rows_rejected=len(issues),
        )
        monthly = repository.fund_issuance_monthly(months=3)
        return {
            "run_id": run_id,
            "rows_written": written,
            "latest_months": [
                {
                    "month": row["month_start"].strftime("%Y-%m"),
                    "fund_count": row["fund_count"],
                    "raised_shares_total": row["raised_shares_total"],
                }
                for row in monthly
            ],
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


def sync_market(
    backfill_days: int = DEFAULT_TURNOVER_BACKFILL_DAYS,
    margin_days: int = 300,
    sleep_seconds: float = DEFAULT_SLEEP_SECONDS,
) -> dict:
    """看盘台市场层的一键同步：各链路独立成败，互不阻塞。"""
    results: dict[str, dict] = {}
    failures: dict[str, str] = {}

    steps = {
        "turnover": lambda: sync_market_turnover(
            backfill_days=backfill_days, sleep_seconds=sleep_seconds
        ),
        "margin": lambda: sync_margin(days=margin_days),
        "valuation": sync_market_valuation,
        "activity": sync_market_activity,
        "index_valuation": sync_index_valuation,
        "fund_issuance": sync_fund_issuance,
    }
    for name, step in steps.items():
        try:
            results[name] = step()
        except Exception as exc:
            failures[name] = str(exc)

    return {"steps": results, "failures": failures}
