from datetime import date, datetime

from etf_engine.config.settings import settings
from etf_engine.db.connection import connect
from etf_engine.research.peer import PEER_CALCULATION_VERSION


class PeerRepository:
    """同类分组与同类分位的读写。"""

    def upsert_groups(self, groups: list[dict]) -> int:
        if not groups:
            return 0
        calculated_at = datetime.now().astimezone()
        rows = [
            (
                group["security_id"],
                group["peer_group_id"],
                group["kind"],
                group.get("label"),
                group["peer_count"],
                PEER_CALCULATION_VERSION,
                calculated_at,
            )
            for group in groups
        ]
        sql = """
        INSERT INTO mart.etf_peer_group (
            security_id, peer_group_id, peer_group_kind, peer_group_label,
            peer_count, calculation_version, calculated_at
        ) VALUES (?,?,?,?,?,?,?)
        ON CONFLICT (security_id) DO UPDATE SET
            peer_group_id = EXCLUDED.peer_group_id,
            peer_group_kind = EXCLUDED.peer_group_kind,
            peer_group_label = EXCLUDED.peer_group_label,
            peer_count = EXCLUDED.peer_count,
            calculation_version = EXCLUDED.calculation_version,
            calculated_at = EXCLUDED.calculated_at
        """
        with connect(settings.database_path) as con:
            con.executemany(sql, rows)
        return len(rows)

    def upsert_metrics(self, records: list[dict]) -> int:
        if not records:
            return 0
        calculated_at = datetime.now().astimezone()
        rows = [
            (
                record["security_id"],
                record["asof_date"],
                record["peer_group_id"],
                record["peer_count"],
                record.get("aum_rank_pct"),
                record.get("turnover_rank_pct"),
                record.get("tracking_error_rank_pct"),
                record.get("fee_rank_pct"),
                record.get("premium_stability_rank_pct"),
                record.get("flow_rank_pct"),
                PEER_CALCULATION_VERSION,
                calculated_at,
            )
            for record in records
        ]
        sql = """
        INSERT INTO mart.etf_peer_metric_daily (
            security_id, asof_date, peer_group_id, peer_count,
            aum_rank_pct, turnover_rank_pct, tracking_error_rank_pct,
            fee_rank_pct, premium_stability_rank_pct, flow_rank_pct,
            calculation_version, calculated_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT (security_id, asof_date, calculation_version) DO UPDATE SET
            peer_group_id = EXCLUDED.peer_group_id,
            peer_count = EXCLUDED.peer_count,
            aum_rank_pct = EXCLUDED.aum_rank_pct,
            turnover_rank_pct = EXCLUDED.turnover_rank_pct,
            tracking_error_rank_pct = EXCLUDED.tracking_error_rank_pct,
            fee_rank_pct = EXCLUDED.fee_rank_pct,
            premium_stability_rank_pct = EXCLUDED.premium_stability_rank_pct,
            flow_rank_pct = EXCLUDED.flow_rank_pct,
            calculated_at = EXCLUDED.calculated_at
        """
        with connect(settings.database_path) as con:
            con.executemany(sql, rows)
        return len(rows)

    def peers_of(self, security_id: str, asof_date: date | None = None) -> dict | None:
        """取某只 ETF 最近的同类分位（按 as-of 截断）。"""
        with connect(settings.database_path) as con:
            row = con.execute(
                """
                SELECT * FROM mart.etf_peer_metric_daily
                WHERE security_id = ?
                  AND (? IS NULL OR asof_date <= ?)
                ORDER BY asof_date DESC
                LIMIT 1
                """,
                [security_id, asof_date, asof_date],
            ).fetchone()
            if row is None:
                return None
            columns = [c[0] for c in con.description]
        return dict(zip(columns, row, strict=True))

    def group_of(self, security_id: str) -> dict | None:
        with connect(settings.database_path) as con:
            row = con.execute(
                "SELECT * FROM mart.etf_peer_group WHERE security_id = ?", [security_id]
            ).fetchone()
            if row is None:
                return None
            columns = [c[0] for c in con.description]
        return dict(zip(columns, row, strict=True))

    def upsert_daily_groups(self, groups: list[dict]) -> int:
        """按日快照写同类分组（Point-in-Time 用）。"""
        if not groups:
            return 0
        calculated_at = datetime.now().astimezone()
        rows = [
            (
                group["security_id"],
                group["asof_date"],
                group["peer_group_id"],
                group["kind"],
                group.get("label"),
                group["peer_count"],
                PEER_CALCULATION_VERSION,
                calculated_at,
            )
            for group in groups
        ]
        sql = """
        INSERT INTO mart.etf_peer_group_daily (
            security_id, asof_date, peer_group_id, peer_group_kind, peer_group_label,
            peer_count, calculation_version, calculated_at
        ) VALUES (?,?,?,?,?,?,?,?)
        ON CONFLICT (security_id, asof_date, calculation_version) DO UPDATE SET
            peer_group_id = EXCLUDED.peer_group_id,
            peer_group_kind = EXCLUDED.peer_group_kind,
            peer_group_label = EXCLUDED.peer_group_label,
            peer_count = EXCLUDED.peer_count,
            calculated_at = EXCLUDED.calculated_at
        """
        with connect(settings.database_path) as con:
            con.executemany(sql, rows)
        return len(rows)

    def group_of_asof(self, security_id: str, asof_date: date | None = None) -> dict | None:
        """Point-in-Time 版同类分组：取 ``asof_date <= requested`` 的最近一份快照。

        没有快照时返回 None（由调用方决定是否回落到"当前分组"并标注置信度），
        不在仓储层偷偷回落到今天。
        """
        with connect(settings.database_path) as con:
            row = con.execute(
                """
                SELECT * FROM mart.etf_peer_group_daily
                WHERE security_id = ?
                  AND (? IS NULL OR asof_date <= ?)
                ORDER BY asof_date DESC
                LIMIT 1
                """,
                [security_id, asof_date, asof_date],
            ).fetchone()
            if row is None:
                return None
            columns = [c[0] for c in con.description]
        return dict(zip(columns, row, strict=True))

    def members_of(self, peer_group_id: str) -> list[str]:
        with connect(settings.database_path) as con:
            rows = con.execute(
                "SELECT security_id FROM mart.etf_peer_group WHERE peer_group_id = ? ORDER BY 1",
                [peer_group_id],
            ).fetchall()
        return [row[0] for row in rows]

    def count(self) -> int:
        with connect(settings.database_path) as con:
            return int(con.execute("SELECT count(*) FROM mart.etf_peer_metric_daily").fetchone()[0])
