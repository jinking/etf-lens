"""构建复权序列（``mart.etf_adjusted_daily``，口径 ``adjust_v1``）。

输入只有两类：``core`` 的未复权事实 + ``core.etf_corporate_action`` 的披露事实。
没有公司行为的标的也会生成序列（因子恒为 1），这样研究层的读取路径只有一条。
"""

from datetime import date, datetime
from decimal import Decimal

from etf_engine.config.settings import settings
from etf_engine.db.connection import connect
from etf_engine.domain.enums import CorporateActionType
from etf_engine.domain.identifiers import SecurityId
from etf_engine.domain.models import ETFCorporateAction, SourceMeta
from etf_engine.domain.quality import DataQualityIssue
from etf_engine.ingestion.run_recorder import IngestionRunRecorder
from etf_engine.repositories.adjusted_series_repository import AdjustedSeriesRepository
from etf_engine.repositories.corporate_action_repository import CorporateActionRepository
from etf_engine.repositories.quality_issue_repository import QualityIssueRepository
from etf_engine.research.adjustment import AdjustmentInputs, build_adjusted_series


def _facts(security_id: str) -> tuple[list, list, list]:
    with connect(settings.database_path) as con:
        closes = con.execute(
            """
            SELECT trade_date, close FROM core.etf_quote_daily
            WHERE security_id = ? ORDER BY trade_date
            """,
            [security_id],
        ).fetchall()
        navs = con.execute(
            """
            SELECT nav_date, unit_nav FROM core.etf_nav_daily
            WHERE security_id = ? ORDER BY nav_date
            """,
            [security_id],
        ).fetchall()
        shares = con.execute(
            """
            SELECT trade_date, shares FROM core.etf_share_daily
            WHERE security_id = ? ORDER BY trade_date
            """,
            [security_id],
        ).fetchall()
    return closes, navs, shares


def _to_actions(rows: list[dict]) -> list[ETFCorporateAction]:
    actions: list[ETFCorporateAction] = []
    fallback_fetched_at = datetime.now().astimezone()
    for row in rows:
        actions.append(
            ETFCorporateAction(
                security_id=row["security_id"],
                action_date=row["action_date"],
                action_type=CorporateActionType(row["action_type"]),
                split_ratio=row.get("split_ratio"),
                nav_adjustment_factor=Decimal(str(row["nav_adjustment_factor"]))
                if row.get("nav_adjustment_factor") is not None
                else None,
                share_adjustment_factor=Decimal(str(row["share_adjustment_factor"]))
                if row.get("share_adjustment_factor") is not None
                else None,
                cash_distribution=Decimal(str(row["cash_distribution"]))
                if row.get("cash_distribution") is not None
                else None,
                source_meta=SourceMeta(
                    source=row.get("source") or "test",
                    fetched_at=row.get("fetched_at") or fallback_fetched_at,
                ),
            )
        )
    return actions


def compute_adjusted_series(
    security_ids: list[str] | None = None,
    asof_date: date | None = None,
) -> dict:
    repository = AdjustedSeriesRepository()
    actions_repository = CorporateActionRepository()
    quality = QualityIssueRepository()
    recorder = IngestionRunRecorder()

    if security_ids:
        targets: list[str] = []
        for item in security_ids:
            try:
                targets.append(SecurityId.parse(item).value)
            except ValueError:
                continue
    else:
        with connect(settings.database_path) as con:
            targets = [
                row[0]
                for row in con.execute(
                    "SELECT DISTINCT security_id FROM core.etf_quote_daily ORDER BY 1"
                ).fetchall()
            ]

    if not targets:
        return {"status": "SKIPPED", "reason": "没有可复权的标的"}

    run_id = recorder.start("etf_adjusted_series", "adjust_v1", asof_date)
    points_written = 0
    issues: list[DataQualityIssue] = []
    funds_with_actions = 0

    for security_id in targets:
        closes, navs, shares = _facts(security_id)
        if not closes and not navs and not shares:
            continue
        action_rows = actions_repository.actions_for(security_id, asof_date=asof_date)
        actions = _to_actions(action_rows)
        if actions:
            funds_with_actions += 1
        elif any(close is not None for _, close in closes):
            # 没有公司行为事实的标的也要有序列（因子恒为 1），
            # 但若原始序列存在未解释的跳变，研究层会拒绝计算（见研究层守卫）。
            pass

        points, point_issues = build_adjusted_series(
            AdjustmentInputs(
                security_id=security_id,
                closes=[
                    (row[0], Decimal(str(row[1]))) if row[1] is not None else (row[0], None)
                    for row in closes
                ],
                navs=[
                    (row[0], Decimal(str(row[1]))) if row[1] is not None else (row[0], None)
                    for row in navs
                ],
                shares=[
                    (row[0], Decimal(str(row[1]))) if row[1] is not None else (row[0], None)
                    for row in shares
                ],
                actions=actions,
            )
        )
        issues.extend(point_issues)
        points_written += repository.upsert_many(points)

    issues_written = quality.record(dataset="etf_adjusted_series", issues=issues)
    recorder.finish(
        run_id,
        status="SUCCESS" if not issues else "PARTIAL",
        rows_fetched=len(targets),
        rows_written=points_written,
        rows_rejected=0,
    )
    return {
        "run_id": run_id,
        "status": "SUCCESS" if not issues else "PARTIAL",
        "target_count": len(targets),
        "rows_written": points_written,
        "funds_with_corporate_actions": funds_with_actions,
        "quality_issues": issues_written,
    }
