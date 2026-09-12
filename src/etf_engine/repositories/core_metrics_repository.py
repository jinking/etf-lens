from datetime import date

from etf_engine.config.settings import settings
from etf_engine.db.connection import connect


class CoreMetricsRepository:
    """Read-only access to standardized facts required by the core metric service."""

    @staticmethod
    def _rows(con, sql: str, values: list) -> list[dict]:
        rows = con.execute(sql, values).fetchall()
        columns = [item[0] for item in con.description]
        return [dict(zip(columns, row, strict=True)) for row in rows]

    def quote_history(self, security_id: str, asof_date: date | None) -> list[dict]:
        with connect(settings.database_path) as con:
            return self._rows(
                con,
                """
                SELECT * FROM core.etf_quote_daily
                WHERE security_id = ? AND (? IS NULL OR trade_date <= ?)
                ORDER BY trade_date
                """,
                [security_id, asof_date, asof_date],
            )

    def share_history(self, security_id: str, asof_date: date) -> list[dict]:
        with connect(settings.database_path) as con:
            return self._rows(
                con,
                """
                SELECT * FROM core.etf_share_daily
                WHERE security_id = ? AND trade_date <= ?
                ORDER BY trade_date
                """,
                [security_id, asof_date],
            )

    def nav_history(self, security_id: str, asof_date: date) -> list[dict]:
        with connect(settings.database_path) as con:
            return self._rows(
                con,
                """
                SELECT * FROM core.etf_nav_daily
                WHERE security_id = ? AND nav_date <= ?
                ORDER BY nav_date
                """,
                [security_id, asof_date],
            )

    def tracking_index(self, security_id: str, asof_date: date) -> dict | None:
        with connect(settings.database_path) as con:
            rows = self._rows(
                con,
                """
                SELECT index_id, index_name, source FROM core.etf_index_map
                WHERE etf_id = ?
                  AND (valid_from IS NULL OR valid_from <= ?)
                  AND (valid_to IS NULL OR valid_to >= ?)
                ORDER BY valid_from DESC NULLS LAST
                LIMIT 1
                """,
                [security_id, asof_date, asof_date],
            )
            if rows:
                return rows[0]
            rows = self._rows(
                con,
                """
                SELECT tracking_index_id AS index_id, tracking_index_name AS index_name, source
                FROM core.etf_master WHERE security_id = ? AND tracking_index_id IS NOT NULL
                """,
                [security_id],
            )
            return rows[0] if rows else None

    def master(self, security_id: str) -> dict | None:
        with connect(settings.database_path) as con:
            rows = self._rows(
                con, "SELECT * FROM core.etf_master WHERE security_id = ?", [security_id]
            )
            return rows[0] if rows else None

    def holdings(
        self, security_id: str, asof_date: date
    ) -> tuple[list[dict], date | None, str | None]:
        with connect(settings.database_path) as con:
            report_dates = self._rows(
                con,
                """
                SELECT MAX(report_date) AS report_date FROM core.etf_holding_disclosure
                WHERE etf_id = ? AND report_date <= ?
                """,
                [security_id, asof_date],
            )
            report_date = report_dates[0]["report_date"] if report_dates else None
            if report_date:
                return (
                    self._rows(
                        con,
                        """
                        SELECT stock_id, stock_name, weight_pct FROM core.etf_holding_disclosure
                        WHERE etf_id = ? AND report_date = ? ORDER BY weight_pct DESC NULLS LAST
                        """,
                        [security_id, report_date],
                    ),
                    report_date,
                    "fund_disclosure",
                )

            mapping = self.tracking_index(security_id, asof_date)
            if mapping is None:
                return [], None, None
            dates = self._rows(
                con,
                """
                SELECT MAX(effective_date) AS effective_date FROM core.index_constituent
                WHERE index_id = ? AND effective_date <= ?
                """,
                [mapping["index_id"], asof_date],
            )
            effective_date = dates[0]["effective_date"] if dates else None
            if not effective_date:
                return [], None, None
            return (
                self._rows(
                    con,
                    """
                    SELECT stock_id, stock_name, weight_pct FROM core.index_constituent
                    WHERE index_id = ? AND effective_date = ? ORDER BY weight_pct DESC NULLS LAST
                    """,
                    [mapping["index_id"], effective_date],
                ),
                effective_date,
                "index_constituent",
            )

    def index_history(self, index_id: str, asof_date: date) -> list[dict]:
        with connect(settings.database_path) as con:
            return self._rows(
                con,
                """
                SELECT * FROM core.index_quote_daily
                WHERE index_id = ? AND trade_date <= ? ORDER BY trade_date
                """,
                [index_id, asof_date],
            )
