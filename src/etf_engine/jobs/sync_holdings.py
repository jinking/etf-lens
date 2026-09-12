from datetime import datetime

from etf_engine.config.settings import settings
from etf_engine.db.connection import connect
from etf_engine.domain.identifiers import SecurityId
from etf_engine.ingestion.run_recorder import IngestionRunRecorder
from etf_engine.repositories.holding_repository import HoldingRepository
from etf_engine.repositories.tag_repository import TagRepository
from etf_engine.services.tagging_service import TaggingService
from etf_engine.sources.akshare.holdings import AkshareETFHoldingSource


def sync_holdings(
    security_ids: list[str] | None = None,
    top_n: int | None = 20,
) -> dict:
    """拉取 ETF 披露前十大持仓，并自动完成行业穿透打标写入 core.etf_tag。"""
    source = AkshareETFHoldingSource()
    holding_repo = HoldingRepository()
    tag_repo = TagRepository()
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
        limit = top_n or 20
        with connect(settings.database_path) as con:
            rows = con.execute(
                """
                SELECT security_id
                FROM (
                    SELECT security_id, turnover_amount,
                           ROW_NUMBER() OVER (PARTITION BY security_id ORDER BY trade_date DESC) as rn
                    FROM core.etf_quote_daily
                )
                WHERE rn = 1
                ORDER BY turnover_amount DESC NULLS LAST
                LIMIT ?
                """,
                [limit],
            ).fetchall()
            targets = [r[0] for r in rows]

    if not targets:
        return {"status": "SKIPPED", "reason": "No target ETFs found"}

    run_id = recorder.start("etf_holdings_and_tags", "holding_penetration", None)
    total_holdings = 0
    total_tags = 0
    errors: list[str] = []

    for sid in targets:
        try:
            holdings = source.fetch_holdings(sid)
            if not holdings:
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
            tags = tagging_service.calculate_industry_tags(sid, holdings_dict, asof_date=holdings[0].report_date)
            written_t = tag_repo.upsert_tags(tags)
            total_tags += written_t

        except Exception as exc:
            errors.append(f"{sid}: {exc}")

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
        "errors": errors,
    }
