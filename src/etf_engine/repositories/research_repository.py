"""Compare / Screener 的只读查询。

SQL 属于 Repository 层：Service 只做参数校验与业务编排，不再直接连接
DuckDB（历史实现把两段长 SQL 写在 ``services/research_service.py`` 里）。
"""

from etf_engine.config.settings import settings
from etf_engine.db.connection import connect

_LATEST_COLUMNS = """
            SELECT *,
                   ROW_NUMBER() OVER (
                       PARTITION BY security_id ORDER BY trade_date DESC
                   ) AS rn
"""


def _latest_cte(name: str, table: str, where: str = "") -> str:
    """构造"每个 security_id 取最新一行"的 CTE，避免四段 SQL 重复八遍。"""
    return f"""
        {name} AS (
            SELECT * EXCLUDE (rn)
            FROM ({_LATEST_COLUMNS}
                FROM {table}
                {where}
            )
            WHERE rn = 1
        )"""


_COMPARE_COLUMNS = """
        SELECT
            m.security_id,
            COALESCE(q.name, m.short_name, m.fund_name) AS fund_name,
            m.manager_name,
            m.fund_type,
            m.tracking_index_name,
            q.close,
            q.change_pct,
            q.turnover_amount,
            met.avg_turnover_amount_20d,
            s.shares,
            s.estimated_aum,
            met.return_20d,
            met.return_60d,
            met.max_drawdown_60d,
            f.share_change_20d,
            f.share_change_pct_20d,
            f.estimated_net_subscription_20d,
            q.trade_date AS quote_asof_date
"""


class ResearchRepository:
    def themes(self, limit: int = 50, min_etf_count: int = 1) -> list[dict]:
        """按标签聚合主题：每个主题下有多少 ETF、合计规模、平均表现。"""
        with connect(settings.database_path) as con:
            rows = con.execute(
                """
                WITH latest_shares AS (
                    SELECT * EXCLUDE (rn)
                    FROM (
                        SELECT *,
                               ROW_NUMBER() OVER (
                                   PARTITION BY security_id ORDER BY trade_date DESC
                               ) AS rn
                        FROM core.etf_share_daily
                    )
                    WHERE rn = 1
                ),
                latest_metrics AS (
                    SELECT * EXCLUDE (rn)
                    FROM (
                        SELECT *,
                               ROW_NUMBER() OVER (
                                   PARTITION BY security_id ORDER BY trade_date DESC
                               ) AS rn
                        FROM mart.etf_metric_daily
                    )
                    WHERE rn = 1
                ),
                latest_flows AS (
                    SELECT * EXCLUDE (rn)
                    FROM (
                        SELECT *,
                               ROW_NUMBER() OVER (
                                   PARTITION BY security_id ORDER BY trade_date DESC
                               ) AS rn
                        FROM mart.etf_flow_daily
                    )
                    WHERE rn = 1
                )
                SELECT
                    t.tag AS theme,
                    t.tag_type,
                    COUNT(DISTINCT t.etf_id) AS etf_count,
                    SUM(s.estimated_aum) AS total_estimated_aum,
                    AVG(m.return_20d) AS avg_return_20d,
                    AVG(f.share_change_pct_20d) AS avg_share_change_pct_20d,
                    MAX(t.coverage) AS max_coverage,
                    MAX(t.calculation_version) AS calculation_version
                FROM core.etf_tag t
                LEFT JOIN latest_shares s ON s.security_id = t.etf_id
                LEFT JOIN latest_metrics m ON m.security_id = t.etf_id
                LEFT JOIN latest_flows f ON f.security_id = t.etf_id
                GROUP BY 1, 2
                HAVING COUNT(DISTINCT t.etf_id) >= ?
                ORDER BY total_estimated_aum DESC NULLS LAST, etf_count DESC
                LIMIT ?
                """,
                [min_etf_count, limit],
            ).fetchall()
            columns = [c[0] for c in con.description]
            return [dict(zip(columns, row, strict=True)) for row in rows]

    def compare(self, security_ids: list[str]) -> list[dict]:
        if not security_ids:
            return []

        placeholders = ",".join(["?"] * len(security_ids))
        latest_ids = f"WHERE security_id IN ({placeholders})"
        ctes = ",\n".join(
            [
                _latest_cte("latest_quotes", "core.etf_quote_daily", latest_ids),
                _latest_cte("latest_shares", "core.etf_share_daily", latest_ids),
                _latest_cte("latest_metrics", "mart.etf_metric_daily", latest_ids),
                _latest_cte("latest_flows", "mart.etf_flow_daily", latest_ids),
            ]
        )
        sql = f"""
        WITH {ctes}
        {_COMPARE_COLUMNS}
        FROM (SELECT unnest([?{", ?" * (len(security_ids) - 1)}]) AS security_id) t
        LEFT JOIN core.etf_master m ON t.security_id = m.security_id
        LEFT JOIN latest_quotes q ON t.security_id = q.security_id
        LEFT JOIN latest_shares s ON t.security_id = s.security_id
        LEFT JOIN latest_metrics met ON t.security_id = met.security_id
        LEFT JOIN latest_flows f ON t.security_id = f.security_id
        """
        params = security_ids * 5

        with connect(settings.database_path) as con:
            rows = con.execute(sql, params).fetchall()
            columns = [c[0] for c in con.description]
            return [dict(zip(columns, r, strict=True)) for r in rows]

    def screen(
        self,
        *,
        query: str | None = None,
        tag: str | None = None,
        min_aum: float | None = None,
        min_turnover_20d: float | None = None,
        min_return_20d: float | None = None,
        max_drawdown_60d: float | None = None,
        share_growth_only: bool = False,
        limit: int = 50,
    ) -> list[dict]:
        where_clauses = ["1=1"]
        values: list = []

        if query:
            where_clauses.append(
                "(m.security_id ILIKE ? OR m.fund_name ILIKE ? OR m.short_name ILIKE ?)"
            )
            pattern = f"%{query}%"
            values.extend([pattern, pattern, pattern])

        if tag:
            where_clauses.append(
                "EXISTS (SELECT 1 FROM core.etf_tag tg "
                "WHERE tg.etf_id = m.security_id AND tg.tag ILIKE ?)"
            )
            values.append(f"%{tag}%")

        if min_aum is not None:
            where_clauses.append("COALESCE(s.estimated_aum, m.reported_aum) >= ?")
            values.append(min_aum)

        if min_turnover_20d is not None:
            where_clauses.append("met.avg_turnover_amount_20d >= ?")
            values.append(min_turnover_20d)

        if min_return_20d is not None:
            where_clauses.append("met.return_20d >= ?")
            values.append(min_return_20d)

        if max_drawdown_60d is not None:
            where_clauses.append("met.max_drawdown_60d >= ?")
            values.append(max_drawdown_60d)

        if share_growth_only:
            where_clauses.append("f.share_change_20d > 0")

        where_stmt = " AND ".join(where_clauses)
        values.append(limit)

        ctes = ",\n".join(
            [
                _latest_cte("latest_quotes", "core.etf_quote_daily"),
                _latest_cte("latest_shares", "core.etf_share_daily"),
                _latest_cte("latest_metrics", "mart.etf_metric_daily"),
                _latest_cte("latest_flows", "mart.etf_flow_daily"),
            ]
        )
        sql = f"""
        WITH {ctes}
        SELECT
            m.security_id,
            COALESCE(q.name, m.short_name, m.fund_name) AS fund_name,
            m.manager_name,
            m.fund_type,
            q.close,
            q.change_pct,
            q.turnover_amount,
            met.avg_turnover_amount_20d,
            COALESCE(s.estimated_aum, m.reported_aum) AS aum,
            met.return_20d,
            met.return_60d,
            met.max_drawdown_60d,
            f.share_change_20d,
            f.estimated_net_subscription_20d,
            (
                SELECT string_agg(tag, ' / ')
                FROM core.etf_tag tg WHERE tg.etf_id = m.security_id
            ) AS tags
        FROM core.etf_master m
        LEFT JOIN latest_quotes q ON m.security_id = q.security_id
        LEFT JOIN latest_shares s ON m.security_id = s.security_id
        LEFT JOIN latest_metrics met ON m.security_id = met.security_id
        LEFT JOIN latest_flows f ON m.security_id = f.security_id
        WHERE {where_stmt}
        ORDER BY q.turnover_amount DESC NULLS LAST, aum DESC NULLS LAST
        LIMIT ?
        """

        with connect(settings.database_path) as con:
            rows = con.execute(sql, values).fetchall()
            columns = [c[0] for c in con.description]
            return [dict(zip(columns, r, strict=True)) for r in rows]
