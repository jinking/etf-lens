from datetime import datetime

from etf_engine.domain.enums import QualityStatus
from etf_engine.domain.identifiers import SecurityId
from etf_engine.domain.models import ETFMaster, ETFShare, SourceMeta
from etf_engine.ingestion.run_recorder import IngestionRunRecorder
from etf_engine.ingestion.source_health import track_source_health
from etf_engine.repositories.master_repository import MasterRepository
from etf_engine.repositories.quote_repository import QuoteRepository
from etf_engine.repositories.share_repository import ShareRepository
from etf_engine.sources.registry import registry


def sync_aum(
    security_ids: list[str] | None = None,
    top_n: int | None = 50,
) -> dict:
    """从权威源 (WeStock/自选股) 同步 ETF 官方披露规模 (reported_aum) 并补充货币 ETF 等份额。"""
    source = registry.westock_profile_source()
    master_repo = MasterRepository()
    share_repo = ShareRepository()
    quote_repo = QuoteRepository()
    recorder = IngestionRunRecorder()

    targets: list[str] = []
    if security_ids:
        for item in security_ids:
            try:
                targets.append(SecurityId.parse(item).value)
            except ValueError:
                continue
    else:
        # 取成交额前 N 只
        base_targets = (
            quote_repo.all_security_ids()
            if top_n is not None and top_n <= 0
            else quote_repo.top_by_turnover(top_n or 50)
        )
        targets = list(base_targets)
        # 始终确保包含常见货币 ETF (511880.SH 银华日利, 511990.SH 华宝添益, 511660.SH 建信添益, 511850.SH 财富宝 等)
        money_etfs = ["511880.SH", "511990.SH", "511660.SH", "511850.SH"]
        for m in money_etfs:
            if m not in targets:
                targets.append(m)

    if not targets:
        return {"status": "SKIPPED", "reason": "No target ETFs found"}

    run_id = recorder.start("etf_aum_and_shares", "westock_profile", None)
    total_aum_written = 0
    total_shares_written = 0
    errors: list[str] = []

    try:
        with track_source_health("westock", "etf_profile"):
            details = source.fetch_aum_and_shares(targets)

        # 1. 确保 master 存在；如果不存在（如货币 ETF）则自动录入 core.etf_master
        fetched_at = datetime.now().astimezone()
        masters_to_insert: list[ETFMaster] = []
        for d in details:
            sid = d["security_id"]
            if master_repo.get_by_id(sid) is None:
                sec_id = SecurityId.parse(sid)
                masters_to_insert.append(
                    ETFMaster(
                        security_id=sid,
                        ticker=sec_id.ticker,
                        exchange=sec_id.exchange.value,
                        fund_name=d.get("fund_name"),
                        short_name=d.get("fund_name"),
                        fund_type=d.get("fund_type") or "货币",
                        manager_name=d.get("manager_name"),
                        custodian_name=d.get("custodian_name"),
                        reported_aum=d.get("reported_aum"),
                        reported_aum_date=d.get("reported_aum_date"),
                        status="ACTIVE",
                        source_meta=SourceMeta(
                            source="westock",
                            upstream_source="tencent",
                            fetched_at=fetched_at,
                            quality_status=QualityStatus.PASS,
                            ingestion_run_id=run_id,
                        ),
                    )
                )
        if masters_to_insert:
            master_repo.upsert_many(masters_to_insert)

        # 2. 批量更新 core.etf_master 中的 reported_aum 与 reported_aum_date
        aum_updates = [
            {
                "security_id": d["security_id"],
                "reported_aum": d["reported_aum"],
                "reported_aum_date": d["reported_aum_date"],
            }
            for d in details
            if d.get("reported_aum") is not None
        ]
        total_aum_written = master_repo.update_reported_aum(aum_updates)

        # 2. 为货币 ETF 或需要补充份额的标的写入 core.etf_share_daily
        shares_to_write: list[ETFShare] = []
        fetched_at = datetime.now().astimezone()
        for d in details:
            if d.get("shares") is not None and d.get("trade_date") is not None:
                # 货币基金或者无场内跟踪份额的 ETF
                is_money = d.get("fund_type") == "货币" or d["security_id"] in (
                    "511880.SH",
                    "511990.SH",
                    "511660.SH",
                    "511850.SH",
                )
                if is_money:
                    shares_to_write.append(
                        ETFShare(
                            security_id=d["security_id"],
                            trade_date=d["trade_date"],
                            fund_name=d.get("fund_name"),
                            shares=d["shares"],
                            nav=d.get("nav"),
                            nav_source="westock/tencent" if d.get("nav") is not None else None,
                            source_meta=SourceMeta(
                                source="westock",
                                upstream_source="tencent",
                                fetched_at=fetched_at,
                                quality_status=QualityStatus.PASS,
                                ingestion_run_id=run_id,
                            ),
                        )
                    )

        if shares_to_write:
            total_shares_written = share_repo.upsert_many(shares_to_write)

    except Exception as exc:
        errors.append(str(exc))

    status = "SUCCESS" if not errors else "FAILED"
    recorder.finish(
        run_id,
        status=status,
        rows_fetched=len(targets),
        rows_written=total_aum_written + total_shares_written,
        rows_rejected=0,
        error_message="; ".join(errors) if errors else None,
    )

    return {
        "run_id": run_id,
        "targets_count": len(targets),
        "aum_updated": total_aum_written,
        "shares_written": total_shares_written,
        "errors": errors,
    }
