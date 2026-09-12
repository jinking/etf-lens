import pandas as pd

from etf_engine.config.settings import settings
from etf_engine.db.connection import connect
from etf_engine.ingestion.run_recorder import IngestionRunRecorder
from etf_engine.repositories.mart_repository import MartRepository
from etf_engine.research.flow import calculate_flow, share_change_pct
from etf_engine.research.liquidity import average_turnover_amount
from etf_engine.research.performance import annualized_volatility, simple_return
from etf_engine.research.risk import current_drawdown, max_drawdown


def compute_mart(security_ids: list[str] | None = None) -> dict:
    mart_repo = MartRepository()
    recorder = IngestionRunRecorder()
    run_id = recorder.start("mart_computation", "internal_engine", None)

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
                    SELECT trade_date, shares, nav
                    FROM core.etf_share_daily
                    WHERE security_id = ?
                    ORDER BY trade_date
                    """,
                    [sid],
                ).fetchall()

                if q_rows:
                    df_q = pd.DataFrame(
                        q_rows, columns=["trade_date", "close", "turnover_amount"]
                    ).set_index("trade_date")
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
                            "calculation_version": "metric_v1",
                        }
                    )

                if s_rows:
                    df_s = pd.DataFrame(s_rows, columns=["trade_date", "shares", "nav"]).set_index(
                        "trade_date"
                    )
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
                            "calculation_version": "flow_v1",
                        }
                    )

        written_metrics = mart_repo.upsert_metrics(metric_records)
        written_flows = mart_repo.upsert_flows(flow_records)

        recorder.finish(
            run_id,
            status="SUCCESS",
            rows_fetched=len(target_ids),
            rows_written=written_metrics + written_flows,
            rows_rejected=0,
        )

        return {
            "run_id": run_id,
            "target_count": len(target_ids),
            "metrics_written": written_metrics,
            "flows_written": written_flows,
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
