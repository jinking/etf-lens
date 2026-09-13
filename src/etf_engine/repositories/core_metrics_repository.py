from datetime import date

from etf_engine.config.settings import settings
from etf_engine.db.connection import connect
from etf_engine.domain.versions import current_flow_version, current_metric_version


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
        """份额历史 + 按同一天对齐的净值。

        份额接口不提供净值时，份额行里的 ``nav`` 只在少数日期上被补齐；
        这里与 ``compute_mart`` 用同一口径（同日 join nav 表）取净值，
        否则估算申赎会因为"净值只差某个日期"而整体变成 NULL。
        """
        with connect(settings.database_path) as con:
            return self._rows(
                con,
                """
                SELECT s.* REPLACE (COALESCE(s.nav, n.unit_nav) AS nav)
                FROM core.etf_share_daily s
                LEFT JOIN core.etf_nav_daily n
                       ON n.security_id = s.security_id AND n.nav_date = s.trade_date
                WHERE s.security_id = ? AND s.trade_date <= ?
                ORDER BY s.trade_date
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

    def adjusted_nav_history(self, security_id: str, asof_date: date) -> list[dict]:
        with connect(settings.database_path) as con:
            return self._rows(
                con,
                """
                SELECT trade_date AS nav_date, adjusted_nav
                FROM mart.etf_adjusted_daily
                WHERE security_id = ? AND trade_date <= ? AND adjusted_nav IS NOT NULL
                ORDER BY trade_date
                """,
                [security_id, asof_date],
            )

    def metric_asof(
        self,
        security_id: str,
        asof_date: date | None = None,
        calculation_version: str | None = None,
    ) -> dict | None:
        version = calculation_version or current_metric_version()
        with connect(settings.database_path) as con:
            rows = self._rows(
                con,
                """
                SELECT * FROM mart.etf_metric_daily
                WHERE security_id = ?
                  AND calculation_version = ?
                  AND (? IS NULL OR trade_date <= ?)
                ORDER BY trade_date DESC
                LIMIT 1
                """,
                [security_id, version, asof_date, asof_date],
            )
            return rows[0] if rows else None

    def flow_asof(
        self,
        security_id: str,
        asof_date: date | None = None,
        calculation_version: str | None = None,
    ) -> dict | None:
        version = calculation_version or current_flow_version()
        with connect(settings.database_path) as con:
            rows = self._rows(
                con,
                """
                SELECT * FROM mart.etf_flow_daily
                WHERE security_id = ?
                  AND calculation_version = ?
                  AND (? IS NULL OR trade_date <= ?)
                ORDER BY trade_date DESC
                LIMIT 1
                """,
                [security_id, version, asof_date, asof_date],
            )
            return rows[0] if rows else None

    def tracking_index(self, security_id: str, asof_date: date | None = None) -> dict | None:
        with connect(settings.database_path) as con:
            rows = self._rows(
                con,
                """
                SELECT index_id, index_name, source FROM core.etf_index_map
                WHERE etf_id = ?
                  AND (? IS NULL OR valid_from IS NULL OR valid_from <= ?)
                  AND (? IS NULL OR valid_to IS NULL OR valid_to > ?)
                ORDER BY valid_from DESC NULLS LAST
                LIMIT 1
                """,
                [security_id, asof_date, asof_date, asof_date, asof_date],
            )
            if rows:
                return rows[0]
            # 历史 as-of 找不到有效映射时直接 None：禁止取未来最近一条 map，再 fallback master。
            if asof_date is not None:
                return None
            # Latest mode 才允许回落
            rows = self._rows(
                con,
                """
                SELECT index_id, index_name, source FROM core.etf_index_map
                WHERE etf_id = ?
                ORDER BY valid_from DESC NULLS LAST
                LIMIT 1
                """,
                [security_id],
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
