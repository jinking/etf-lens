from dataclasses import dataclass

from etf_engine.config.settings import settings
from etf_engine.db.connection import connect
from etf_engine.domain.identifiers import SecurityId


class ResearchService:
    """提供 ETF 批量对比 (Compare) 与条件筛选 (Screener) 统一服务。"""

    def compare(self, security_ids: list[str]) -> list[dict]:
        if not security_ids:
            return []

        canonical_ids = []
        for sid in security_ids:
            try:
                canonical_ids.append(SecurityId.parse(sid).value)
            except ValueError:
                continue

        if not canonical_ids:
            return []

        placeholders = ",".join(["?"] * len(canonical_ids))
        sql = f"""
        WITH latest_quotes AS (
            SELECT * EXCLUDE (rn)
            FROM (
                SELECT *, ROW_NUMBER() OVER (PARTITION BY security_id ORDER BY trade_date DESC) as rn
                FROM core.etf_quote_daily
                WHERE security_id IN ({placeholders})
            )
            WHERE rn = 1
        ),
        latest_shares AS (
            SELECT * EXCLUDE (rn)
            FROM (
                SELECT *, ROW_NUMBER() OVER (PARTITION BY security_id ORDER BY trade_date DESC) as rn
                FROM core.etf_share_daily
                WHERE security_id IN ({placeholders})
            )
            WHERE rn = 1
        ),
        latest_metrics AS (
            SELECT * EXCLUDE (rn)
            FROM (
                SELECT *, ROW_NUMBER() OVER (PARTITION BY security_id ORDER BY trade_date DESC) as rn
                FROM mart.etf_metric_daily
                WHERE security_id IN ({placeholders})
            )
            WHERE rn = 1
        ),
        latest_flows AS (
            SELECT * EXCLUDE (rn)
            FROM (
                SELECT *, ROW_NUMBER() OVER (PARTITION BY security_id ORDER BY trade_date DESC) as rn
                FROM mart.etf_flow_daily
                WHERE security_id IN ({placeholders})
            )
            WHERE rn = 1
        )
        SELECT
            m.security_id,
            COALESCE(q.name, m.short_name, m.fund_name) as fund_name,
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
            q.trade_date as quote_asof_date
        FROM (SELECT unnest([?{', ?' * (len(canonical_ids)-1)}]) as security_id) t
        LEFT JOIN core.etf_master m ON t.security_id = m.security_id
        LEFT JOIN latest_quotes q ON t.security_id = q.security_id
        LEFT JOIN latest_shares s ON t.security_id = s.security_id
        LEFT JOIN latest_metrics met ON t.security_id = met.security_id
        LEFT JOIN latest_flows f ON t.security_id = f.security_id
        """
        params = canonical_ids * 5

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
            where_clauses.append("(m.security_id ILIKE ? OR m.fund_name ILIKE ? OR m.short_name ILIKE ?)")
            pattern = f"%{query}%"
            values.extend([pattern, pattern, pattern])

        if tag:
            where_clauses.append("EXISTS (SELECT 1 FROM core.etf_tag tg WHERE tg.etf_id = m.security_id AND tg.tag ILIKE ?)")
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

        sql = f"""
        WITH latest_quotes AS (
            SELECT * EXCLUDE (rn)
            FROM (

                SELECT *, ROW_NUMBER() OVER (PARTITION BY security_id ORDER BY trade_date DESC) as rn
                FROM core.etf_quote_daily
            )
            WHERE rn = 1
        ),
        latest_shares AS (
            SELECT * EXCLUDE (rn)
            FROM (
                SELECT *, ROW_NUMBER() OVER (PARTITION BY security_id ORDER BY trade_date DESC) as rn
                FROM core.etf_share_daily
            )
            WHERE rn = 1
        ),
        latest_metrics AS (
            SELECT * EXCLUDE (rn)
            FROM (
                SELECT *, ROW_NUMBER() OVER (PARTITION BY security_id ORDER BY trade_date DESC) as rn
                FROM mart.etf_metric_daily
            )
            WHERE rn = 1
        ),
        latest_flows AS (
            SELECT * EXCLUDE (rn)
            FROM (
                SELECT *, ROW_NUMBER() OVER (PARTITION BY security_id ORDER BY trade_date DESC) as rn
                FROM mart.etf_flow_daily
            )
            WHERE rn = 1
        )
        SELECT
            m.security_id,
            COALESCE(q.name, m.short_name, m.fund_name) as fund_name,
            m.manager_name,
            m.fund_type,
            q.close,
            q.change_pct,
            q.turnover_amount,
            met.avg_turnover_amount_20d,
            COALESCE(s.estimated_aum, m.reported_aum) as aum,
            met.return_20d,
            met.return_60d,
            met.max_drawdown_60d,
            f.share_change_20d,
            f.estimated_net_subscription_20d,
            (SELECT string_agg(tag, ' / ') FROM core.etf_tag tg WHERE tg.etf_id = m.security_id) as tags
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
