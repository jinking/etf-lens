"""Compare / Screener 的只读查询。

SQL 属于 Repository 层：Service 只做参数校验与业务编排，不直接连接 DuckDB。

时间纪律（V2 Phase 1 Point-in-Time）：

* 每张表只取 ``trade_date <= asof_date`` 的最新一行，不回看未来；
* 每条结果都带出**各数据块自己的** as-of 日期与口径版本；
* 新鲜度裁剪（``max_staleness_days`` / ``require_same_trade_date`` / 口径版本校验）
  由 :func:`etf_engine.domain.research_context.apply_context` 统一执行，
  Compare 与 Screener 共用同一套判定，避免两条路径口径分叉。
"""

from etf_engine.config.settings import settings
from etf_engine.db.connection import connect
from etf_engine.domain.research_context import ResearchContext
from etf_engine.domain.versions import current_flow_version, current_metric_version

_LATEST_COLUMNS = """
            SELECT *,
                   ROW_NUMBER() OVER (
                       PARTITION BY security_id ORDER BY trade_date DESC
                   ) AS rn
"""


def _latest_cte(
    name: str,
    table: str,
    *,
    where: str | None = None,
    date_column: str = "trade_date",
    versioned: bool = False,
) -> str:
    """ "每个 security_id 取 as-of 之前最新一行"的 CTE。

    两个 ``?`` 都是 as-of 参数：为空表示"取最新可得"（兼容既有行为），
    非空则严格 ``<= asof_date``。
    """
    conditions = [where] if where else []
    conditions.append(f"(? IS NULL OR {date_column} <= ?)")
    if versioned:
        # 同一天可能同时存在多个口径版本：必须由业务显式指定，
        # 不能让"最新一行"的竞争由数据库决定。
        conditions.append("calculation_version = ?")
    return f"""
        {name} AS (
            SELECT * EXCLUDE (rn)
            FROM ({_LATEST_COLUMNS}
                FROM {table}
                WHERE {" AND ".join(conditions)}
            )
            WHERE rn = 1
        )"""


def _cte_params(context: ResearchContext, *, version: str | None = None) -> list[object]:
    """一个 CTE 的参数：两个 as-of 占位符 +（可选）口径版本。"""
    params: list[object] = [context.asof_date, context.asof_date]
    if version is not None:
        params.append(version)
    return params


_COMPARE_SELECT = """
        SELECT
            m.security_id,
            COALESCE(q.name, m.short_name, m.fund_name) AS fund_name,
            m.manager_name,
            m.fund_type,
            COALESCE(
                (
                    SELECT im.index_name FROM core.etf_index_map im
                    WHERE im.etf_id = m.security_id
                      AND (? IS NULL OR im.valid_from IS NULL OR im.valid_from <= ?)
                      AND (? IS NULL OR im.valid_to IS NULL OR im.valid_to > ?)
                    ORDER BY im.valid_from DESC NULLS LAST
                    LIMIT 1
                ),
                m.tracking_index_name
            ) AS tracking_index_name,
            CASE
                WHEN EXISTS (
                    SELECT 1 FROM core.etf_index_map im
                    WHERE im.etf_id = m.security_id
                      AND (? IS NULL OR im.valid_from IS NULL OR im.valid_from <= ?)
                      AND (? IS NULL OR im.valid_to IS NULL OR im.valid_to > ?)
                ) THEN 'mapped_asof'
                WHEN m.tracking_index_name IS NOT NULL THEN 'master_latest'
                ELSE NULL
            END AS tracking_index_pit,
            CASE
                WHEN m.profile_observed_at IS NULL THEN NULL
                WHEN ? IS NULL OR m.profile_observed_at <= CAST(? AS TIMESTAMP)
                    THEN m.management_fee_pct
            END AS management_fee_pct,
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
            q.trade_date AS quote_asof_date,
            s.trade_date AS share_asof_date,
            met.trade_date AS metric_asof_date,
            f.trade_date AS flow_asof_date,
            met.calculation_version AS metric_calculation_version,
            f.calculation_version AS flow_calculation_version
"""

_SCREEN_SELECT = """
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
                FROM core.etf_tag tg
                WHERE tg.etf_id = m.security_id
                  AND (? IS NULL OR tg.valid_from IS NULL OR tg.valid_from <= ?)
                  AND (? IS NULL OR tg.valid_to IS NULL OR tg.valid_to > ?)
            ) AS tags,
            COALESCE(
                (
                    SELECT im.index_name FROM core.etf_index_map im
                    WHERE im.etf_id = m.security_id
                      AND (? IS NULL OR im.valid_from IS NULL OR im.valid_from <= ?)
                      AND (? IS NULL OR im.valid_to IS NULL OR im.valid_to > ?)
                    ORDER BY im.valid_from DESC NULLS LAST
                    LIMIT 1
                ),
                m.tracking_index_name
            ) AS tracking_index_name,
            CASE
                WHEN EXISTS (
                    SELECT 1 FROM core.etf_index_map im
                    WHERE im.etf_id = m.security_id
                      AND (? IS NULL OR im.valid_from IS NULL OR im.valid_from <= ?)
                      AND (? IS NULL OR im.valid_to IS NULL OR im.valid_to > ?)
                ) THEN 'mapped_asof'
                WHEN m.tracking_index_name IS NOT NULL THEN 'master_latest'
                ELSE NULL
            END AS tracking_index_pit,
            q.trade_date AS quote_asof_date,
            s.trade_date AS share_asof_date,
            met.trade_date AS metric_asof_date,
            f.trade_date AS flow_asof_date,
            met.calculation_version AS metric_calculation_version,
            f.calculation_version AS flow_calculation_version
"""


class ResearchRepository:
    def themes(
        self,
        limit: int = 50,
        min_etf_count: int = 1,
        context: ResearchContext | None = None,
    ) -> list[dict]:
        """按标签聚合主题：每个主题下有多少 ETF、合计规模、平均表现。

        同样是 Point-in-Time：三张事实表都只取 as-of 之前的最新一行，
        并回报各块实际用到的日期。
        """
        context = context or ResearchContext()
        ctes = ",\n".join(
            [
                _latest_cte("latest_shares", "core.etf_share_daily"),
                _latest_cte("latest_metrics", "mart.etf_metric_daily", versioned=True),
                _latest_cte("latest_flows", "mart.etf_flow_daily", versioned=True),
            ]
        )
        params: list = _cte_params(context)
        params.extend(_cte_params(context, version=current_metric_version()))
        params.extend(_cte_params(context, version=current_flow_version()))
        params.extend([min_etf_count, limit])

        with connect(settings.database_path) as con:
            rows = con.execute(
                f"""
                WITH {ctes}
                SELECT
                    t.tag AS theme,
                    t.tag_type,
                    COUNT(DISTINCT t.etf_id) AS etf_count,
                    SUM(s.estimated_aum) AS total_estimated_aum,
                    AVG(m.return_20d) AS avg_return_20d,
                    AVG(f.share_change_pct_20d) AS avg_share_change_pct_20d,
                    MAX(t.coverage) AS max_coverage,
                    MAX(t.calculation_version) AS calculation_version,
                    MAX(s.trade_date) AS share_asof_date,
                    MAX(m.trade_date) AS metric_asof_date,
                    MAX(f.trade_date) AS flow_asof_date
                FROM core.etf_tag t
                LEFT JOIN latest_shares s ON s.security_id = t.etf_id
                LEFT JOIN latest_metrics m ON m.security_id = t.etf_id
                LEFT JOIN latest_flows f ON f.security_id = t.etf_id
                GROUP BY 1, 2
                HAVING COUNT(DISTINCT t.etf_id) >= ?
                ORDER BY total_estimated_aum DESC NULLS LAST, etf_count DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
            columns = [c[0] for c in con.description]
            return [dict(zip(columns, row, strict=True)) for row in rows]

    def compare(
        self, security_ids: list[str], context: ResearchContext | None = None
    ) -> list[dict]:
        if not security_ids:
            return []

        context = context or ResearchContext()
        placeholders = ",".join(["?"] * len(security_ids))
        latest_ids = f"security_id IN ({placeholders})"
        ctes = ",\n".join(
            [
                _latest_cte("latest_quotes", "core.etf_quote_daily", where=latest_ids),
                _latest_cte("latest_shares", "core.etf_share_daily", where=latest_ids),
                _latest_cte(
                    "latest_metrics", "mart.etf_metric_daily", where=latest_ids, versioned=True
                ),
                _latest_cte(
                    "latest_flows", "mart.etf_flow_daily", where=latest_ids, versioned=True
                ),
            ]
        )
        params: list = []
        params.extend([*security_ids, *_cte_params(context)])  # quote
        params.extend([*security_ids, *_cte_params(context)])  # share
        params.extend([*security_ids, *_cte_params(context, version=current_metric_version())])
        params.extend([*security_ids, *_cte_params(context, version=current_flow_version())])
        # SELECT 子句里的 as-of 占位：跟踪指数映射(2) + PIT 标记(2) + 档案观测(2)
        params.extend(_cte_params(context) * 5)

        sql = f"""
        WITH {ctes}
        {_COMPARE_SELECT}
        FROM (SELECT unnest([?{", ?" * (len(security_ids) - 1)}]) AS security_id) t
        LEFT JOIN core.etf_master m ON t.security_id = m.security_id
        LEFT JOIN latest_quotes q ON t.security_id = q.security_id
        LEFT JOIN latest_shares s ON t.security_id = s.security_id
        LEFT JOIN latest_metrics met ON t.security_id = met.security_id
        LEFT JOIN latest_flows f ON t.security_id = f.security_id
        """
        params.extend(security_ids)

        with connect(settings.database_path) as con:
            rows = con.execute(sql, params).fetchall()
            columns = [c[0] for c in con.description]
            return [dict(zip(columns, r, strict=True)) for r in rows]

    def screen_candidates(
        self,
        *,
        context: ResearchContext | None = None,
        query: str | None = None,
        tag: str | None = None,
    ) -> list[dict]:
        """取候选行：as-of 截断 + 关键词/标签过滤。

        数值条件故意**不**下推到 SQL：它们必须在新鲜度裁剪之后才判定，
        否则一条已经过期（被策略置空）的记录仍可能通过阈值条件。
        """
        context = context or ResearchContext()
        where_clauses = ["1=1"]
        values: list = []

        if query:
            where_clauses.append(
                "(m.security_id ILIKE ? OR m.fund_name ILIKE ? OR m.short_name ILIKE ?)"
            )
            pattern = f"%{query}%"
            values.extend([pattern, pattern, pattern])

        if tag:
            # 标签是带有效期的（valid_from / valid_to）：按 as-of 过滤，
            # 否则历史研究会被"今天才打上的标签"污染。
            where_clauses.append(
                "EXISTS (SELECT 1 FROM core.etf_tag tg "
                "WHERE tg.etf_id = m.security_id AND tg.tag ILIKE ? "
                "  AND (? IS NULL OR tg.valid_from IS NULL OR tg.valid_from <= ?) "
                "  AND (? IS NULL OR tg.valid_to IS NULL OR tg.valid_to > ?))"
            )
            values.append(f"%{tag}%")
            values.extend(_cte_params(context) * 2)

        ctes = ",\n".join(
            [
                _latest_cte("latest_quotes", "core.etf_quote_daily"),
                _latest_cte("latest_shares", "core.etf_share_daily"),
                _latest_cte("latest_metrics", "mart.etf_metric_daily", versioned=True),
                _latest_cte("latest_flows", "mart.etf_flow_daily", versioned=True),
            ]
        )
        params: list = []
        params.extend(_cte_params(context))
        params.extend(_cte_params(context))
        params.extend(_cte_params(context, version=current_metric_version()))
        params.extend(_cte_params(context, version=current_flow_version()))
        # SELECT 子句：标签(4) + 跟踪指数名(2) + PIT 标记(2) = 8
        params.extend(_cte_params(context) * 6)
        params.extend(values)

        sql = f"""
        WITH {ctes}
        {_SCREEN_SELECT}
        FROM core.etf_master m
        LEFT JOIN latest_quotes q ON m.security_id = q.security_id
        LEFT JOIN latest_shares s ON m.security_id = s.security_id
        LEFT JOIN latest_metrics met ON m.security_id = met.security_id
        LEFT JOIN latest_flows f ON m.security_id = f.security_id
        WHERE {" AND ".join(where_clauses)}
        """

        with connect(settings.database_path) as con:
            rows = con.execute(sql, params).fetchall()
            columns = [c[0] for c in con.description]
            return [dict(zip(columns, r, strict=True)) for r in rows]
