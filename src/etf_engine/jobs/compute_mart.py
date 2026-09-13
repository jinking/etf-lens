import pandas as pd

from etf_engine.config.settings import settings
from etf_engine.db.connection import connect
from etf_engine.domain.quality import error
from etf_engine.domain.versions import FLOW_VERSION, METRIC_VERSION
from etf_engine.ingestion.run_recorder import IngestionRunRecorder
from etf_engine.jobs.sync_calendar import ensure_market_calendar
from etf_engine.repositories.mart_repository import MartRepository
from etf_engine.repositories.quality_issue_repository import QualityIssueRepository
from etf_engine.research.flow import calculate_flow, share_change_pct
from etf_engine.research.liquidity import average_turnover_amount
from etf_engine.research.performance import annualized_volatility, simple_return
from etf_engine.research.risk import current_drawdown, max_drawdown


def _drop_non_trading_days(df: pd.DataFrame, calendar, kind: str, security_id: str):
    """剔除日期不在交易日历里的观测，并留痕。

    为什么要剔除而不是报错放弃：非交易日只可能来自错误的日期推断
    （历史上深交所份额快照就把周六写了进库）。直接用它算指标会造出一条
    "周六的数据"并长期污染 mart；而整只 ETF 直接跳过又会丢掉合法的历史。
    因此这里剔除非法日期、保留其余观测，并把剔除动作写进 quality_issue。
    """
    invalid = [day for day in df.index if calendar.covers(day) and not calendar.is_trading_day(day)]
    issues = [
        error(
            f"{kind}_trade_date_not_trading_day",
            f"{security_id} trade_date={day.isoformat()} 不是交易日，已从指标计算中剔除",
        )
        for day in invalid
    ]
    if invalid:
        df = df.drop(index=invalid)
    return df, issues


def compute_mart(security_ids: list[str] | None = None) -> dict:
    mart_repo = MartRepository()
    quality_repo = QualityIssueRepository()
    recorder = IngestionRunRecorder()
    calendar = ensure_market_calendar()
    run_id = recorder.start("mart_computation", "internal_engine", None)
    rejected = 0
    issues = []

    try:
        # 整批计算复用同一个连接：历史上每只 ETF 各开一次 DuckDB 连接，
        # 全市场 1500+ 只 ETF 就是 1500+ 次 open/close。
        with connect(settings.database_path) as con:
            if security_ids:
                placeholders = ",".join(["?"] * len(security_ids))
                query = (
                    "SELECT DISTINCT security_id FROM core.etf_quote_daily "
                    f"WHERE security_id IN ({placeholders})"
                )
                rows = con.execute(query, security_ids).fetchall()
            else:
                query = "SELECT DISTINCT security_id FROM core.etf_quote_daily"
                rows = con.execute(query).fetchall()
            target_ids = [r[0] for r in rows]

            metric_records: list[dict] = []
            flow_records: list[dict] = []

            for sid in target_ids:
                q_rows = con.execute(
                    """
                    SELECT trade_date, close, turnover_amount
                    FROM core.etf_quote_daily
                    WHERE security_id = ?
                    ORDER BY trade_date
                    """,
                    [sid],
                ).fetchall()

                s_rows = con.execute(
                    """
                    SELECT s.trade_date,
                           s.shares,
                           COALESCE(s.nav, n.unit_nav) AS nav
                    FROM core.etf_share_daily s
                    LEFT JOIN core.etf_nav_daily n
                           ON n.security_id = s.security_id
                          AND n.nav_date = s.trade_date
                    WHERE s.security_id = ?
                    ORDER BY s.trade_date
                    """,
                    [sid],
                ).fetchall()

                if q_rows:
                    df_q = pd.DataFrame(
                        q_rows, columns=["trade_date", "close", "turnover_amount"]
                    ).set_index("trade_date")
                    df_q, invalid_q = _drop_non_trading_days(df_q, calendar, "metric", sid)
                    rejected += len(invalid_q)
                    issues.extend(invalid_q)

                if q_rows and not df_q.empty:
                    latest_trade_date = df_q.index[-1]
                    metric_records.append(
                        {
                            "security_id": sid,
                            "trade_date": latest_trade_date,
                            "return_1d": simple_return(df_q["close"], 1),
                            "return_5d": simple_return(df_q["close"], 5),
                            "return_20d": simple_return(df_q["close"], 20),
                            "return_60d": simple_return(df_q["close"], 60),
                            "volatility_20d": annualized_volatility(df_q["close"], 20),
                            "volatility_60d": annualized_volatility(df_q["close"], 60),
                            "max_drawdown_60d": max_drawdown(df_q["close"], 60),
                            "max_drawdown_250d": max_drawdown(df_q["close"], 250),
                            "current_drawdown": current_drawdown(df_q["close"]),
                            "avg_turnover_amount_5d": average_turnover_amount(
                                df_q["turnover_amount"], 5
                            ),
                            "avg_turnover_amount_20d": average_turnover_amount(
                                df_q["turnover_amount"], 20
                            ),
                            "avg_turnover_amount_60d": average_turnover_amount(
                                df_q["turnover_amount"], 60
                            ),
                            "calculation_version": METRIC_VERSION,
                        }
                    )

                if s_rows:
                    df_s = pd.DataFrame(s_rows, columns=["trade_date", "shares", "nav"]).set_index(
                        "trade_date"
                    )
                    df_s, invalid_s = _drop_non_trading_days(df_s, calendar, "flow", sid)
                    rejected += len(invalid_s)
                    issues.extend(invalid_s)

                if s_rows and not df_s.empty:
                    latest_share_date = df_s.index[-1]
                    flow = calculate_flow(df_s["shares"], df_s["nav"])

                    flow_records.append(
                        {
                            "security_id": sid,
                            "trade_date": latest_share_date,
                            "share_change_1d": flow.share_change_1d,
                            "share_change_pct_1d": flow.share_change_pct_1d,
                            "share_change_5d": flow.share_change_5d,
                            "share_change_20d": flow.share_change_20d,
                            "share_change_60d": flow.share_change_60d,
                            "share_change_pct_5d": share_change_pct(df_s["shares"], 5),
                            "share_change_pct_20d": share_change_pct(df_s["shares"], 20),
                            "share_change_pct_60d": share_change_pct(df_s["shares"], 60),
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

        written_metrics = mart_repo.upsert_metrics(metric_records)
        written_flows = mart_repo.upsert_flows(flow_records)

        issues_written = quality_repo.record(dataset="mart_computation", issues=issues)

        recorder.finish(
            run_id,
            status="SUCCESS" if not rejected else "PARTIAL",
            rows_fetched=len(target_ids),
            rows_written=written_metrics + written_flows,
            rows_rejected=rejected,
        )

        return {
            "run_id": run_id,
            "target_count": len(target_ids),
            "metrics_written": written_metrics,
            "flows_written": written_flows,
            "rows_rejected": rejected,
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
