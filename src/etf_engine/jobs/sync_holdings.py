from etf_engine.domain.identifiers import SecurityId
from etf_engine.domain.quality import error, warn
from etf_engine.ingestion.run_recorder import IngestionRunRecorder
from etf_engine.ingestion.source_health import track_source_health
from etf_engine.repositories.holding_repository import HoldingRepository
from etf_engine.repositories.quality_issue_repository import QualityIssueRepository
from etf_engine.repositories.quote_repository import QuoteRepository
from etf_engine.repositories.tag_repository import TagRepository
from etf_engine.services.tagging_service import TaggingService
from etf_engine.sources.registry import registry


def sync_holdings(
    security_ids: list[str] | None = None,
    top_n: int | None = 20,
) -> dict:
    """拉取 ETF 披露前十大持仓，并自动完成行业穿透打标写入 core.etf_tag。

    ``top_n <= 0`` 表示覆盖本地有行情的全部 ETF（逐只请求，耗时长，建议显式使用）。
    """
    source = registry.holding_source()
    holding_repo = HoldingRepository()
    tag_repo = TagRepository()
    quality_repo = QualityIssueRepository()
    tagging_service = TaggingService()
    recorder = IngestionRunRecorder()

    targets: list[str] = []
    if security_ids:
        for item in security_ids:
            try:
                targets.append(SecurityId.parse(item).value)
            except ValueError:
                continue
    else:
        quote_repository = QuoteRepository()
        targets = (
            quote_repository.all_security_ids()
            if top_n is not None and top_n <= 0
            else quote_repository.top_by_turnover(top_n or 20)
        )

    if not targets:
        return {"status": "SKIPPED", "reason": "No target ETFs found"}

    run_id = recorder.start("etf_holdings_and_tags", "holding_penetration", None)
    total_holdings = 0
    total_tags = 0
    total_issues = 0
    errors: list[str] = []

    for sid in targets:
        try:
            with track_source_health("akshare/eastmoney", "etf_holding"):
                holdings, parse_issues = source.fetch_holdings_with_issues(sid)
            total_issues += quality_repo.record(
                dataset="etf_holding",
                issues=parse_issues,
                security_id=None if holdings else sid,
                trade_date=holdings[0].report_date if holdings else None,
            )
            if not holdings:
                total_issues += quality_repo.record(
                    dataset="etf_holding",
                    issues=[warn("holding_disclosure_unavailable", f"{sid} 未取得披露持仓")],
                    security_id=sid,
                )
                continue

            for h in holdings:
                h.source_meta.ingestion_run_id = run_id

            written_h = holding_repo.upsert_many(holdings)
            total_holdings += written_h

            # 穿透加权计算行业暴露
            holdings_dict = [
                {
                    "stock_id": h.stock_id,
                    "stock_name": h.stock_name,
                    "weight_pct": h.weight_pct,
                }
                for h in holdings
            ]
            tags = tagging_service.calculate_industry_tags(
                sid, holdings_dict, asof_date=holdings[0].report_date
            )
            written_t = tag_repo.upsert_tags(tags)
            total_tags += written_t

        except Exception as exc:
            errors.append(f"{sid}: {exc}")
            total_issues += quality_repo.record(
                dataset="etf_holding",
                issues=[error("holding_fetch_failed", f"{sid}: {exc}")],
                security_id=sid,
            )

    status = "SUCCESS" if not errors else ("PARTIAL" if total_holdings > 0 else "FAILED")
    recorder.finish(
        run_id,
        status=status,
        rows_fetched=total_holdings,
        rows_written=total_holdings + total_tags,
        rows_rejected=0,
        error_message="; ".join(errors) if errors else None,
    )

    return {
        "run_id": run_id,
        "targets_count": len(targets),
        "holdings_written": total_holdings,
        "tags_written": total_tags,
        "quality_issues": total_issues,
        "errors": errors,
    }
