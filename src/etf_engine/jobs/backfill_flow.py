"""按份额历史逐日回填申赎估算（``mart.etf_flow_daily``）。

为什么需要单独回填：日常的 ``compute_mart`` 每只 ETF 只写"最新一天"一行，
所以 mart 里的申赎历史是靠每天跑一次攒出来的。想把**篮子净申购的历史**画出来
（状态历史热力图要用），就得拿已有的份额事实做一次回放。

回放口径：

* 只回放**份额事实存在**且**是交易日**的日期；
* 每一天都用"截至当日的份额/净值前缀"计算，等价于当天就算过——
  ``calculate_flow`` 只回看有限窗口，前缀结果与全量结果一致；
* 估算值仍带 ``is_estimated`` 与 ``calculation_version=flow_v1``，
  不因为是回填就降级口径。
"""

import pandas as pd

from etf_engine.config.settings import settings
from etf_engine.db.connection import connect
from etf_engine.domain.quality import error
from etf_engine.domain.versions import FLOW_V2_VERSION, FLOW_VERSION
from etf_engine.ingestion.run_recorder import IngestionRunRecorder
from etf_engine.jobs.sync_calendar import ensure_market_calendar
from etf_engine.repositories.mart_repository import MartRepository
from etf_engine.repositories.quality_issue_repository import QualityIssueRepository
from etf_engine.research.flow import calculate_flow, share_change_pct
from etf_engine.research.flow_v2 import flow_v2_windows


def _share_rows(security_ids: list[str] | None) -> dict[str, list[tuple]]:
    """一次读完需要的份额序列 + 复权序列，避免逐只 ETF 各开一次连接。"""
    sql = """
    SELECT s.security_id, s.trade_date, s.shares, COALESCE(s.nav, n.unit_nav) AS nav
    FROM core.etf_share_daily s
    LEFT JOIN core.etf_nav_daily n
           ON n.security_id = s.security_id AND n.nav_date = s.trade_date
    """
    values: list = []
    if security_ids:
        placeholders = ",".join("?" for _ in security_ids)
        sql += f" WHERE s.security_id IN ({placeholders})"
        values = list(security_ids)
    sql += " ORDER BY s.security_id, s.trade_date"

    with connect(settings.database_path) as con:
        rows = con.execute(sql, values).fetchall()

    grouped: dict[str, list[tuple]] = {}
    for security_id, trade_date, shares, nav in rows:
        grouped.setdefault(security_id, []).append((trade_date, shares, nav))
    return grouped


def _adjusted_rows(security_ids: list[str] | None = None) -> dict[str, pd.DataFrame]:
    """复权序列（``adjust_v1``）。没有复权序列的标的走 v1 口径，不硬造 v2。"""
    sql = """
    SELECT security_id, trade_date, adjusted_shares, adjusted_nav, adjustment_factor
    FROM mart.etf_adjusted_daily
    """
    values: list = []
    if security_ids:
        placeholders = ",".join("?" for _ in security_ids)
        sql += f" WHERE security_id IN ({placeholders})"
        values = list(security_ids)
    sql += " ORDER BY security_id, trade_date"

    with connect(settings.database_path) as con:
        rows = con.execute(sql, values).fetchall()

    grouped: dict[str, pd.DataFrame] = {}
    for security_id, trade_date, adj_shares, adj_nav, factor in rows:
        grouped.setdefault(security_id, []).append(
            {
                "trade_date": trade_date,
                "adjusted_shares": adj_shares,
                "adjusted_nav": adj_nav,
                "adjustment_factor": factor,
            }
        )
    return {
        security_id: pd.DataFrame(items).set_index("trade_date").sort_index()
        for security_id, items in grouped.items()
    }


def backfill_flow_history(security_ids: list[str] | None = None) -> dict:
    calendar = ensure_market_calendar()
    mart_repo = MartRepository()
    quality_repo = QualityIssueRepository()
    recorder = IngestionRunRecorder()
    run_id = recorder.start("etf_flow_history", "internal_engine", None)
    try:
        grouped = _share_rows(security_ids)
        adjusted_grouped = _adjusted_rows(security_ids)
        records: list[dict] = []
        issues = []
        adjusted_records = 0

        for security_id, rows in grouped.items():
            invalid = [
                row
                for row in rows
                if calendar.covers(row[0]) and not calendar.is_trading_day(row[0])
            ]
            for row in invalid:
                issues.append(
                    error(
                        "flow_trade_date_not_trading_day",
                        f"{security_id} trade_date={row[0].isoformat()} 不是交易日，已跳过回填",
                    )
                )
            invalid_dates = {row[0] for row in invalid}
            valid = [row for row in rows if row[0] not in invalid_dates]
            if not valid:
                continue

            frame = pd.DataFrame(valid, columns=["trade_date", "shares", "nav"]).set_index(
                "trade_date"
            )
            for position, trade_date in enumerate(frame.index):
                prefix = frame.iloc[: position + 1]
                flow = calculate_flow(prefix["shares"], prefix["nav"])
                records.append(
                    {
                        "security_id": security_id,
                        "trade_date": trade_date,
                        "share_change_1d": flow.share_change_1d,
                        "share_change_pct_1d": flow.share_change_pct_1d,
                        "share_change_5d": flow.share_change_5d,
                        "share_change_20d": flow.share_change_20d,
                        "share_change_60d": flow.share_change_60d,
                        "share_change_pct_5d": share_change_pct(prefix["shares"], 5),
                        "share_change_pct_20d": share_change_pct(prefix["shares"], 20),
                        "share_change_pct_60d": share_change_pct(prefix["shares"], 60),
                        "estimated_net_subscription_1d": flow.estimated_net_subscription_1d,
                        "estimated_net_subscription_5d": flow.estimated_net_subscription_5d,
                        "estimated_net_subscription_20d": flow.estimated_net_subscription_20d,
                        "estimated_net_subscription_60d": flow.estimated_net_subscription_60d,
                        "consecutive_share_inflow_days": flow.consecutive_share_inflow_days,
                        "consecutive_share_outflow_days": flow.consecutive_share_outflow_days,
                        "is_estimated": True,
                        "calculation_version": FLOW_VERSION,
                    }
                )

            # v2：按复权序列逐日回放，剔除折算造成的机械份额变化。
            # 与 v1 并存（版本不覆盖历史口径）；没有复权序列的标的跳过。
            adjusted = adjusted_grouped.get(security_id)
            if adjusted is not None and not adjusted.empty:
                # 只在"有份额事实"的日期写资金流行：份额缺失的日子谈不上资金流，
                # 写了就会变成没有来源的孤儿派生行。
                share_dates = {row[0] for row in valid}
                for position, trade_date in enumerate(adjusted.index):
                    if trade_date not in share_dates:
                        continue
                    prefix = adjusted.iloc[: position + 1]
                    metrics, quality = flow_v2_windows(prefix)
                    records.append(
                        {
                            "security_id": security_id,
                            "trade_date": trade_date,
                            "share_change_1d": metrics.get("share_change_1d"),
                            "share_change_pct_1d": metrics.get("share_change_pct_1d"),
                            "share_change_5d": metrics.get("share_change_5d"),
                            "share_change_20d": metrics.get("share_change_20d"),
                            "share_change_60d": metrics.get("share_change_60d"),
                            "share_change_pct_5d": metrics.get("share_change_pct_5d"),
                            "share_change_pct_20d": metrics.get("share_change_pct_20d"),
                            "share_change_pct_60d": metrics.get("share_change_pct_60d"),
                            "estimated_net_subscription_1d": metrics.get("estimated_1d"),
                            "estimated_net_subscription_5d": metrics.get("estimated_5d"),
                            "estimated_net_subscription_20d": metrics.get("estimated_20d"),
                            "estimated_net_subscription_60d": metrics.get("estimated_60d"),
                            "consecutive_share_inflow_days": metrics.get("inflow_days"),
                            "consecutive_share_outflow_days": metrics.get("outflow_days"),
                            "is_estimated": True,
                            "calculation_version": FLOW_V2_VERSION,
                            "flow_quality_status": quality,
                        }
                    )
                    adjusted_records += 1

        written = mart_repo.upsert_flows(records)
        # 清理没有份额事实支撑的派生行：份额缺失的日子谈不上资金流。
        # 这类行只可能来自更早的实现或刻意裁剪过的份额数据，且随时可重算。
        with connect(settings.database_path) as con:
            before = con.execute("SELECT count(*) FROM mart.etf_flow_daily").fetchone()[0]
            con.execute(
                """
                DELETE FROM mart.etf_flow_daily f
                WHERE NOT EXISTS (
                    SELECT 1 FROM core.etf_share_daily s
                    WHERE s.security_id = f.security_id AND s.trade_date = f.trade_date
                )
                """
            )
            after = con.execute("SELECT count(*) FROM mart.etf_flow_daily").fetchone()[0]
        orphans_removed = before - after
        issues_written = quality_repo.record(dataset="etf_flow_history", issues=issues)
        recorder.finish(
            run_id,
            status="SUCCESS",
            rows_fetched=len(records),
            rows_written=written,
            rows_rejected=len(issues),
        )
        dates = sorted({record["trade_date"] for record in records})
        return {
            "run_id": run_id,
            "etf_count": len(grouped),
            "rows_written": written,
            "v2_rows": adjusted_records,
            "orphans_removed": orphans_removed,
            "date_range": ([dates[0].isoformat(), dates[-1].isoformat()] if dates else None),
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
