from datetime import datetime

from etf_engine.config.settings import settings
from etf_engine.db.connection import connect
from etf_engine.domain.versions import FLOW_VERSION, METRIC_VERSION


class MartRepository:
    def upsert_metrics(self, records: list[dict]) -> int:
        if not records:
            return 0

        rows = []
        now = datetime.now().astimezone()
        for r in records:
            rows.append(
                (
                    r["security_id"],
                    r["trade_date"],
                    r.get("return_1d"),
                    r.get("return_5d"),
                    r.get("return_20d"),
                    r.get("return_60d"),
                    r.get("volatility_20d"),
                    r.get("volatility_60d"),
                    r.get("max_drawdown_60d"),
                    r.get("max_drawdown_250d"),
                    r.get("current_drawdown"),
                    r.get("avg_turnover_amount_5d"),
                    r.get("avg_turnover_amount_20d"),
                    r.get("avg_turnover_amount_60d"),
                    r.get("calculation_version", METRIC_VERSION),
                    now,
                )
            )

        sql = """
        INSERT INTO mart.etf_metric_daily (
            security_id, trade_date, return_1d, return_5d, return_20d, return_60d,
            volatility_20d, volatility_60d, max_drawdown_60d, max_drawdown_250d,
            current_drawdown, avg_turnover_amount_5d, avg_turnover_amount_20d,
            avg_turnover_amount_60d, calculation_version, calculated_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT (security_id, trade_date, calculation_version) DO UPDATE SET
            return_1d = EXCLUDED.return_1d,
            return_5d = EXCLUDED.return_5d,
            return_20d = EXCLUDED.return_20d,
            return_60d = EXCLUDED.return_60d,
            volatility_20d = EXCLUDED.volatility_20d,
            volatility_60d = EXCLUDED.volatility_60d,
            max_drawdown_60d = EXCLUDED.max_drawdown_60d,
            max_drawdown_250d = EXCLUDED.max_drawdown_250d,
            current_drawdown = EXCLUDED.current_drawdown,
            avg_turnover_amount_5d = EXCLUDED.avg_turnover_amount_5d,
            avg_turnover_amount_20d = EXCLUDED.avg_turnover_amount_20d,
            avg_turnover_amount_60d = EXCLUDED.avg_turnover_amount_60d,
            calculated_at = EXCLUDED.calculated_at
        """

        with connect(settings.database_path) as con:
            con.executemany(sql, rows)
        return len(rows)

    def upsert_flows(self, records: list[dict]) -> int:
        if not records:
            return 0

        rows = []
        now = datetime.now().astimezone()
        for r in records:
            rows.append(
                (
                    r["security_id"],
                    r["trade_date"],
                    r.get("share_change_1d"),
                    r.get("share_change_pct_1d"),
                    r.get("share_change_5d"),
                    r.get("share_change_20d"),
                    r.get("share_change_60d"),
                    r.get("share_change_pct_5d"),
                    r.get("share_change_pct_20d"),
                    r.get("share_change_pct_60d"),
                    r.get("estimated_net_subscription_1d"),
                    r.get("estimated_net_subscription_5d"),
                    r.get("estimated_net_subscription_20d"),
                    r.get("estimated_net_subscription_60d"),
                    r.get("consecutive_share_inflow_days"),
                    r.get("consecutive_share_outflow_days"),
                    r.get("is_estimated", True),
                    r.get("calculation_version", FLOW_VERSION),
                    now,
                )
            )

        sql = """
        INSERT INTO mart.etf_flow_daily (
            security_id, trade_date, share_change_1d, share_change_pct_1d,
            share_change_5d, share_change_20d, share_change_60d,
            share_change_pct_5d, share_change_pct_20d, share_change_pct_60d,
            estimated_net_subscription_1d, estimated_net_subscription_5d,
            estimated_net_subscription_20d, estimated_net_subscription_60d,
            consecutive_share_inflow_days, consecutive_share_outflow_days,
            is_estimated, calculation_version, calculated_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT (security_id, trade_date, calculation_version) DO UPDATE SET
            share_change_1d = EXCLUDED.share_change_1d,
            share_change_pct_1d = EXCLUDED.share_change_pct_1d,
            share_change_5d = EXCLUDED.share_change_5d,
            share_change_20d = EXCLUDED.share_change_20d,
            share_change_60d = EXCLUDED.share_change_60d,
            share_change_pct_5d = EXCLUDED.share_change_pct_5d,
            share_change_pct_20d = EXCLUDED.share_change_pct_20d,
            share_change_pct_60d = EXCLUDED.share_change_pct_60d,
            estimated_net_subscription_1d = EXCLUDED.estimated_net_subscription_1d,
            estimated_net_subscription_5d = EXCLUDED.estimated_net_subscription_5d,
            estimated_net_subscription_20d = EXCLUDED.estimated_net_subscription_20d,
            estimated_net_subscription_60d = EXCLUDED.estimated_net_subscription_60d,
            consecutive_share_inflow_days = EXCLUDED.consecutive_share_inflow_days,
            consecutive_share_outflow_days = EXCLUDED.consecutive_share_outflow_days,
            is_estimated = EXCLUDED.is_estimated,
            calculated_at = EXCLUDED.calculated_at
        """

        with connect(settings.database_path) as con:
            con.executemany(sql, rows)
        return len(rows)

    def get_latest_metrics(self, security_id: str) -> dict | None:
        with connect(settings.database_path) as con:
            row = con.execute(
                """
                SELECT * FROM mart.etf_metric_daily
                WHERE security_id = ?
                ORDER BY trade_date DESC LIMIT 1
                """,
                [security_id],
            ).fetchone()
            if not row:
                return None
            columns = [c[0] for c in con.description]
            return dict(zip(columns, row, strict=True))

    def get_latest_flow(self, security_id: str) -> dict | None:
        with connect(settings.database_path) as con:
            row = con.execute(
                """
                SELECT * FROM mart.etf_flow_daily
                WHERE security_id = ?
                ORDER BY trade_date DESC LIMIT 1
                """,
                [security_id],
            ).fetchone()
            if not row:
                return None
            columns = [c[0] for c in con.description]
            return dict(zip(columns, row, strict=True))
