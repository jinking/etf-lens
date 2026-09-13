"""计算同类分组与同类分位（``peer_v1``）。

输入全部来自已落库的事实与派生：跟踪指数（master / index_map）、规模与成交额
（quote/share + mart）、跟踪误差（core metrics 同款算法）、费率（fund_profile）、
折溢价稳定性（quote 的 premium_discount_pct_normalized）、资金流（mart.flow）。

没有任何"综合评分"，也不给买卖建议——只输出同类分位。
"""

from datetime import date

import pandas as pd

from etf_engine.config.settings import settings
from etf_engine.db.connection import connect
from etf_engine.domain.enums import BenchmarkReturnBasis
from etf_engine.ingestion.run_recorder import IngestionRunRecorder
from etf_engine.repositories.peer_repository import PeerRepository
from etf_engine.research.benchmark import premium_stats
from etf_engine.research.peer import (
    MIN_PEER_COUNT,
    RANK_DIRECTIONS,
    assign_peer_group,
    group_members,
    percentile,
)
from etf_engine.research.tracking import classify_benchmark_basis, tracking_error


def _candidates(asof: date | None) -> list[dict]:
    """候选池：有行情、且能判定同类依据的 ETF。"""
    with connect(settings.database_path) as con:
        rows = con.execute(
            """
            WITH latest_quote AS (
                SELECT security_id, MAX(trade_date) AS trade_date
                FROM core.etf_quote_daily
                WHERE (? IS NULL OR trade_date <= ?)
                GROUP BY 1
            ),
            latest_share AS (
                SELECT security_id, estimated_aum,
                       ROW_NUMBER() OVER (
                           PARTITION BY security_id ORDER BY trade_date DESC
                       ) AS rn
                FROM core.etf_share_daily
                WHERE (? IS NULL OR trade_date <= ?)
            ),
            latest_flow AS (
                SELECT security_id, share_change_20d,
                       ROW_NUMBER() OVER (
                           PARTITION BY security_id ORDER BY trade_date DESC
                       ) AS rn
                FROM mart.etf_flow_daily
                WHERE (? IS NULL OR trade_date <= ?)
            ),
            primary_tag AS (
                SELECT etf_id, MIN(tag) AS tag
                FROM core.etf_tag
                WHERE tag_type = 'industry'
                GROUP BY 1
            )
            SELECT
                m.security_id,
                m.tracking_index_id,
                m.tracking_index_name,
                m.management_fee_pct,
                t.tag AS primary_tag,
                q.trade_date AS quote_asof_date,
                s.estimated_aum,
                f.share_change_20d
            FROM core.etf_master m
            JOIN latest_quote q ON q.security_id = m.security_id
            LEFT JOIN latest_share s ON s.security_id = m.security_id AND s.rn = 1
            LEFT JOIN latest_flow f ON f.security_id = m.security_id AND f.rn = 1
            LEFT JOIN primary_tag t ON t.etf_id = m.security_id
            """,
            [asof, asof, asof, asof, asof, asof],
        ).fetchall()
        columns = [c[0] for c in con.description]
    return [dict(zip(columns, row, strict=True)) for row in rows]


def _turnover_series(security_id: str, asof: date | None, window: int = 20) -> float | None:
    with connect(settings.database_path) as con:
        rows = con.execute(
            """
            SELECT turnover_amount FROM core.etf_quote_daily
            WHERE security_id = ? AND (? IS NULL OR trade_date <= ?)
            ORDER BY trade_date DESC
            LIMIT ?
            """,
            [security_id, asof, asof, window],
        ).fetchall()
    values = [row[0] for row in rows if row[0] is not None]
    if len(values) < window:
        return None
    return float(sum(values) / len(values))


def _premium_series(security_id: str, asof: date | None, window: int = 20) -> list[float]:
    with connect(settings.database_path) as con:
        rows = con.execute(
            """
            SELECT premium_discount_pct_normalized FROM core.etf_quote_daily
            WHERE security_id = ? AND premium_discount_pct_normalized IS NOT NULL
              AND (? IS NULL OR trade_date <= ?)
            ORDER BY trade_date DESC
            LIMIT ?
            """,
            [security_id, asof, asof, window],
        ).fetchall()
    return [row[0] for row in rows]


def _tracking_error(
    security_id: str, index_id: str | None, index_name: str | None, asof: date | None
) -> float | None:
    if not index_id:
        return None
    with connect(settings.database_path) as con:
        nav_rows = con.execute(
            """
            SELECT nav_date, COALESCE(adjusted_nav, unit_nav) AS nav
            FROM core.etf_nav_daily
            WHERE security_id = ? AND (? IS NULL OR nav_date <= ?)
            ORDER BY nav_date
            """,
            [security_id, asof, asof],
        ).fetchall()
        index_rows = con.execute(
            """
            SELECT trade_date, close FROM core.index_quote_daily
            WHERE index_id = ? AND (? IS NULL OR trade_date <= ?)
            ORDER BY trade_date
            """,
            [index_id, asof, asof],
        ).fetchall()
    if not nav_rows or not index_rows:
        return None
    if classify_benchmark_basis(index_name) is not BenchmarkReturnBasis.PRICE_INDEX:
        # 口径未知/全收益：跟踪误差的分母口径不确定，宁可不给。
        return None
    nav = pd.Series([row[1] for row in nav_rows], index=[row[0] for row in nav_rows])
    index = pd.Series([row[1] for row in index_rows], index=[row[0] for row in index_rows])
    return tracking_error(nav, index, window=60)


def compute_peer_metrics(asof: date | None = None) -> dict:
    repository = PeerRepository()
    recorder = IngestionRunRecorder()
    run_id = recorder.start("peer_metrics", "internal_engine", asof)

    try:
        candidates = _candidates(asof)
        # 指数目录里的"名称 → 代码"：让只有跟踪标的名、没有代码的 ETF 也能和
        # 拿到代码的同类分到一组（否则同一指数会被拆成两个组）。
        with connect(settings.database_path) as con:
            catalog_rows = con.execute(
                "SELECT index_id, index_name FROM core.index_catalog"
            ).fetchall()
        name_to_index = {name: index_id for index_id, name in catalog_rows if name}

        groups = []
        facts: dict[str, dict] = {}
        asof_date = asof or date.today()

        for row in candidates:
            tracking_index_id = row.get("tracking_index_id")
            if not tracking_index_id and row.get("tracking_index_name"):
                tracking_index_id = name_to_index.get(row["tracking_index_name"])
            group = assign_peer_group(
                security_id=row["security_id"],
                tracking_index_id=tracking_index_id,
                tracking_index_name=row.get("tracking_index_name"),
                primary_tag=row.get("primary_tag"),
            )
            if group is None:
                continue
            groups.append(group)
            premium = premium_stats(pd.Series(_premium_series(row["security_id"], asof)), window=20)
            facts[row["security_id"]] = {
                "aum": row.get("estimated_aum"),
                "turnover": _turnover_series(row["security_id"], asof),
                "tracking_error": _tracking_error(
                    row["security_id"],
                    row.get("tracking_index_id"),
                    row.get("tracking_index_name"),
                    asof,
                ),
                "fee": row.get("management_fee_pct"),
                "premium_stability": premium.std,
                "flow": row.get("share_change_20d"),
                "asof_date": row.get("quote_asof_date") or asof_date,
            }

        members = group_members(groups)
        group_rows = [
            {
                "security_id": group.security_id,
                "peer_group_id": group.peer_group_id,
                "kind": group.kind,
                "label": group.label,
                "peer_count": len(members[group.peer_group_id]),
            }
            for group in groups
        ]
        repository.upsert_groups(group_rows)
        # 同时写按日快照：历史 as-of 查询用得上（V2.1 Phase 4）。
        repository.upsert_daily_groups([{**row, "asof_date": asof_date} for row in group_rows])

        metric_rows: list[dict] = []
        for group_id, security_ids in members.items():
            if len(security_ids) < MIN_PEER_COUNT:
                continue
            values = {key: [facts[sid].get(key) for sid in security_ids] for key in RANK_DIRECTIONS}
            for security_id in security_ids:
                own = facts[security_id]
                metric_rows.append(
                    {
                        "security_id": security_id,
                        "asof_date": own["asof_date"],
                        "peer_group_id": group_id,
                        "peer_count": len(security_ids),
                        "aum_rank_pct": percentile(
                            values["aum"], own.get("aum"), higher_is_better=True
                        ),
                        "turnover_rank_pct": percentile(
                            values["turnover"], own.get("turnover"), higher_is_better=True
                        ),
                        "tracking_error_rank_pct": percentile(
                            values["tracking_error"],
                            own.get("tracking_error"),
                            higher_is_better=False,
                        ),
                        "fee_rank_pct": percentile(
                            values["fee"], own.get("fee"), higher_is_better=False
                        ),
                        "premium_stability_rank_pct": percentile(
                            values["premium_stability"],
                            own.get("premium_stability"),
                            higher_is_better=False,
                        ),
                        "flow_rank_pct": percentile(
                            values["flow"], own.get("flow"), higher_is_better=True
                        ),
                    }
                )

        written = repository.upsert_metrics(metric_rows)
        recorder.finish(
            run_id,
            status="SUCCESS",
            rows_fetched=len(candidates),
            rows_written=len(group_rows) + written,
            rows_rejected=0,
        )
        return {
            "run_id": run_id,
            "candidate_count": len(candidates),
            "group_count": len(members),
            "groups_written": len(group_rows),
            "metrics_written": written,
            "skipped_small_groups": sum(1 for ids in members.values() if len(ids) < MIN_PEER_COUNT),
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
