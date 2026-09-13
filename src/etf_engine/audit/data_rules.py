"""数据库不变量：把 ``AGENTS.md`` 的数据纪律变成可执行检查。

覆盖的纪律：

* 第 4 条：缺失值用 NULL，不用 0 代替；
* 第 6 条：估算值必须带 ``is_estimated`` 与 ``calculation_version``；
* 第 7 条：持仓必须带披露日期；
* 第 8 条：公式变化必须升 ``calculation_version``（同一张表不许混版本）；
* 交易日纪律：任何行情/派生行的日期都必须是交易日；
* 可追溯：每行事实都要有 ``source`` / ``fetched_at``。

每条规则返回违规明细（最多带若干样本），空列表表示通过。
"""

from dataclasses import dataclass
from pathlib import Path

from etf_engine.config.settings import settings
from etf_engine.db.connection import connect
from etf_engine.domain.versions import REGISTERED_VERSIONS

SEVERITY_ERROR = "ERROR"
SEVERITY_WARN = "WARN"


@dataclass(frozen=True, slots=True)
class DataRule:
    name: str
    severity: str
    description: str


DATA_RULES = (
    DataRule(
        "rows_on_non_trading_days",
        SEVERITY_ERROR,
        "行情/派生行的日期必须出现在 core.trading_calendar（非交易日只可能来自错误的日期推断）",
    ),
    DataRule(
        "orphan_mart_rows",
        SEVERITY_ERROR,
        "mart 派生行必须能对应到 core 事实（否则是历史脏数据的残留）",
    ),
    DataRule(
        "estimates_without_version",
        SEVERITY_ERROR,
        "估算值必须 is_estimated = true 且 calculation_version 非空",
    ),
    DataRule(
        "mixed_calculation_versions",
        SEVERITY_WARN,
        "派生表里出现未登记的口径版本（已登记版本允许并存：历史口径保留 + 新口径并行）",
    ),
    DataRule(
        "zero_substituted_for_unknown",
        SEVERITY_ERROR,
        "不可能为 0 的字段出现 0：多半是拿 0 顶替了缺失",
    ),
    DataRule(
        "missing_source_metadata",
        SEVERITY_ERROR,
        "事实行必须带 source 与 fetched_at，保证可追溯",
    ),
    DataRule(
        "holdings_without_report_date",
        SEVERITY_ERROR,
        "持仓必须带披露报告期（公开持仓不是实时组合）——由 schema 约束兜底，"
        "这条规则负责检查约束还在不在（schema 漂移会让纪律静默失效）",
    ),
    DataRule(
        "incomplete_market_turnover",
        SEVERITY_WARN,
        "沪深两市成交额应当成对出现；只落一边说明上游缺了一边",
    ),
    DataRule(
        "future_data_in_research_snapshot",
        SEVERITY_ERROR,
        "研究派生行不得领先于它依赖的事实：mart 的日期若晚于对应 core 事实的"
        "最新日期，说明用到了当时还不存在的数据（Point-in-Time 违规）",
    ),
    DataRule(
        "unadjusted_flow_crosses_corporate_action",
        SEVERITY_ERROR,
        "资金流行跨越了份额拆分/折算却没走 v2 口径：机械份额变化会被误读成申购",
    ),
    DataRule(
        "adjusted_series_missing_version",
        SEVERITY_ERROR,
        "复权序列必须登记 calculation_version，且必须是已登记版本（口径不可无主）",
    ),
    DataRule(
        "adjusted_series_future_action_leak",
        SEVERITY_ERROR,
        "复权因子只能用截至当日（含）的公司行为推算：历史时点不得被未来才知道的"
        "公司行为改写（Point-in-Time 泄漏）",
    ),
)


def _scalar(con, sql: str, values: list | None = None):
    row = con.execute(sql, values or []).fetchone()
    return row[0] if row else None


def _table_exists(con, table: str) -> bool:
    """表存在才检查。

    迁移尚未执行的库（例如刚升级、还没 `etf db-init`）不应该让自检直接崩掉；
    这些规则在迁移生效后自然开始工作。
    """
    schema, _, name = table.partition(".")
    return bool(
        _scalar(
            con,
            """
            SELECT COUNT(*) FROM information_schema.tables
            WHERE table_schema = ? AND table_name = ?
            """,
            [schema, name],
        )
    )


def _rows(con, sql: str, values: list | None = None) -> list[tuple]:
    # 显式转成 tuple：DuckDB 返回的是它自己的行对象，注解成 list[tuple] 会骗 mypy。
    return [tuple(row) for row in con.execute(sql, values or []).fetchall()]


def _non_trading_day_violations(con) -> list[dict]:
    """日期不在交易日历里的行（日历没有覆盖该区间时跳过判定）。"""
    targets = [
        ("core.etf_quote_daily", "trade_date"),
        ("core.etf_share_daily", "trade_date"),
        ("core.market_turnover_daily", "trade_date"),
        ("core.margin_balance_daily", "trade_date"),
        ("core.market_activity_daily", "trade_date"),
        ("mart.etf_metric_daily", "trade_date"),
        ("mart.etf_flow_daily", "trade_date"),
        ("mart.market_pulse_daily", "trade_date"),
    ]
    calendar_bounds = _rows(
        con,
        "SELECT MIN(trade_date), MAX(trade_date) FROM core.trading_calendar",
    )
    if not calendar_bounds or calendar_bounds[0][0] is None:
        return [{"dataset": "core.trading_calendar", "detail": "交易日历为空，无法判定"}]

    first_day, last_day = calendar_bounds[0]
    violations: list[dict] = []
    for table, column in targets:
        rows = _rows(
            con,
            f"""
            SELECT DISTINCT {column} AS trade_date
            FROM {table}
            WHERE {column} IS NOT NULL
              AND {column} BETWEEN ? AND ?
              AND {column} NOT IN (SELECT trade_date FROM core.trading_calendar)
            ORDER BY 1
            """,
            [first_day, last_day],
        )
        for (trade_date,) in rows:
            violations.append({"dataset": table, "detail": f"{trade_date} 不是交易日"})
    return violations


def _orphan_mart_violations(con) -> list[dict]:
    checks = [
        (
            "mart.etf_flow_daily",
            "core.etf_share_daily",
            "份额事实",
        ),
        (
            "mart.etf_metric_daily",
            "core.etf_quote_daily",
            "行情事实",
        ),
    ]
    violations: list[dict] = []
    for mart_table, core_table, label in checks:
        rows = _rows(
            con,
            f"""
            SELECT m.security_id, m.trade_date
            FROM {mart_table} m
            LEFT JOIN {core_table} c
                   ON c.security_id = m.security_id AND c.trade_date = m.trade_date
            WHERE c.security_id IS NULL
            LIMIT 20
            """,
        )
        for security_id, trade_date in rows:
            violations.append(
                {
                    "dataset": mart_table,
                    "detail": f"{security_id} {trade_date} 没有对应的{label}",
                }
            )
    return violations


def _estimate_version_violations(con) -> list[dict]:
    rows = _rows(
        con,
        """
        SELECT security_id, trade_date
        FROM mart.etf_flow_daily
        WHERE COALESCE(is_estimated, FALSE) = FALSE
           OR calculation_version IS NULL
           OR calculation_version = ''
        LIMIT 20
        """,
    )
    return [
        {
            "dataset": "mart.etf_flow_daily",
            "detail": f"{security_id} {trade_date} 估算标记或口径版本缺失",
        }
        for security_id, trade_date in rows
    ]


def _mixed_version_violations(con) -> list[dict]:
    """派生表里出现了**未登记**的口径版本。

    V2 起允许同一张表并存多个**已登记**版本（metric_v1 与 metric_v2、
    flow_v1 与 flow_v2），历史口径保留、新口径并行——"混版本"本身不再是问题。
    真正危险的是出现没在 ``domain/versions.py`` 登记过的版本：那意味着有人改了
    公式却没留版本号，历史数据再也解释不清。
    """
    violations: list[dict] = []
    for table, column in (
        ("mart.etf_flow_daily", "calculation_version"),
        ("mart.etf_metric_daily", "calculation_version"),
        ("mart.market_pulse_daily", "calculation_version"),
    ):
        if not _table_exists(con, table):
            continue
        rows = _rows(con, f"SELECT DISTINCT {column} FROM {table}")
        unregistered = sorted(
            value for (value,) in rows if value is not None and value not in REGISTERED_VERSIONS
        )
        if unregistered:
            violations.append(
                {
                    "dataset": table,
                    "detail": "未登记的口径版本：" + "、".join(unregistered),
                }
            )
    return violations


def _zero_substitution_violations(con) -> list[dict]:
    checks = [
        ("core.etf_share_daily", "shares <= 0", "shares"),
        ("core.etf_share_daily", "nav <= 0", "nav"),
        ("core.etf_nav_daily", "unit_nav <= 0", "unit_nav"),
        ("core.etf_quote_daily", "iopv <= 0", "iopv"),
        ("core.market_turnover_daily", "turnover_amount <= 0", "turnover_amount"),
        ("core.margin_balance_daily", "margin_balance <= 0", "margin_balance"),
    ]
    violations: list[dict] = []
    for table, condition, column in checks:
        count = _scalar(con, f"SELECT COUNT(*) FROM {table} WHERE {condition}")
        if count:
            violations.append(
                {
                    "dataset": table,
                    "detail": f"{column} 有 {count} 行 <= 0（缺失应记 NULL，不该填 0）",
                }
            )
    return violations


def _missing_source_metadata_violations(con) -> list[dict]:
    tables = (
        "core.etf_quote_daily",
        "core.etf_share_daily",
        "core.market_turnover_daily",
        "core.margin_balance_daily",
        "core.market_activity_daily",
        "core.index_quote_daily",
    )
    violations: list[dict] = []
    for table in tables:
        count = _scalar(
            con,
            f"""
            SELECT COUNT(*) FROM {table}
            WHERE source IS NULL OR source = '' OR fetched_at IS NULL
            """,
        )
        if count:
            violations.append({"dataset": table, "detail": f"{count} 行缺少 source / fetched_at"})
    return violations


def _holdings_without_report_date(con) -> list[dict]:
    """检查"持仓必须带报告期"这条纪律是否还被 schema 兜住。

    ``report_date`` 在主键里且 NOT NULL，所以**数据层面已经不可能缺失**；
    这条规则改成 schema 守卫：一旦有人把 NOT NULL 去掉，立即报警。
    同类的还有 ``source`` / ``fetched_at`` 的 NOT NULL。
    """
    # pragma_table_info 返回 (cid, name, type, notnull, dflt_value, pk)
    columns = {
        row[1]: row
        for row in _rows(con, "SELECT * FROM pragma_table_info('core.etf_holding_disclosure')")
    }
    column = columns.get("report_date")
    if column is None:
        return [
            {
                "dataset": "core.etf_holding_disclosure",
                "detail": "表不存在或缺少 report_date 列",
            }
        ]
    # pragma_table_info 的第 4 列是 notnull（0/1）
    if not column[3]:
        return [
            {
                "dataset": "core.etf_holding_disclosure",
                "detail": "report_date 丢失了 NOT NULL 约束：持仓披露期可能被写成空值",
            }
        ]

    count = _scalar(
        con,
        "SELECT COUNT(*) FROM core.etf_holding_disclosure WHERE report_date IS NULL",
    )
    if not count:
        return []
    return [{"dataset": "core.etf_holding_disclosure", "detail": f"{count} 行没有 report_date"}]


def _incomplete_turnover_violations(con) -> list[dict]:
    rows = _rows(
        con,
        """
        SELECT trade_date, COUNT(DISTINCT exchange) AS exchanges
        FROM core.market_turnover_daily
        GROUP BY trade_date
        HAVING COUNT(DISTINCT exchange) < 2
        ORDER BY trade_date DESC
        LIMIT 10
        """,
    )
    return [
        {
            "dataset": "core.market_turnover_daily",
            "detail": f"{trade_date} 只落了 {exchanges} 个交易所",
        }
        for trade_date, exchanges in rows
    ]


def _future_data_violations(con) -> list[dict]:
    """派生行不得领先于其依赖的事实（Point-in-Time 违规）。

    一一对应关系：

    * ``mart.etf_metric_daily`` ← ``core.etf_quote_daily``（收益/波动/回撤的来源）
    * ``mart.etf_flow_daily``   ← ``core.etf_share_daily``（份额变化的来源）
    """
    checks = (
        (
            "mart.etf_metric_daily",
            "core.etf_quote_daily",
        ),
        (
            "mart.etf_flow_daily",
            "core.etf_share_daily",
        ),
    )
    violations: list[dict] = []
    for derived, fact in checks:
        rows = _rows(
            con,
            f"""
            SELECT d.security_id, d.trade_date, f.latest_fact_date
            FROM {derived} d
            JOIN (
                SELECT security_id, MAX(trade_date) AS latest_fact_date
                FROM {fact}
                GROUP BY security_id
            ) f ON f.security_id = d.security_id
            WHERE d.trade_date > f.latest_fact_date
            ORDER BY d.trade_date DESC
            LIMIT 10
            """,
        )
        violations.extend(
            {
                "dataset": derived,
                "detail": f"{security_id} 派生到 {trade_date}，但 {fact} 只到 {latest_fact_date}",
            }
            for security_id, trade_date, latest_fact_date in rows
        )
    return violations


def _flow_crosses_action_violations(con) -> list[dict]:
    """有折算的日期缺少 flow_v2 口径 → 机械份额变化只能被当成申赎。

    v1 行是保留的历史口径，本身不算违规；真正的问题是：某个 (标的, 日期)
    落在折算窗口内，却**没有**对应的 v2 行——那么唯一可读的口径就是被污染的 v1。
    """
    if not (
        _table_exists(con, "core.etf_corporate_action")
        and _table_exists(con, "mart.etf_flow_daily")
    ):
        return []
    rows = _rows(
        con,
        """
        SELECT f.security_id, f.trade_date, f.calculation_version, a.action_date
        FROM mart.etf_flow_daily f
        JOIN core.etf_corporate_action a
          ON a.security_id = f.security_id
         AND a.action_date <= f.trade_date
         AND a.action_date > f.trade_date - INTERVAL 60 DAY
         AND a.share_adjustment_factor IS NOT NULL
         AND a.share_adjustment_factor <> 1
        WHERE f.calculation_version <> 'flow_v2'
          AND (
                f.share_change_1d IS NOT NULL
             OR f.share_change_5d IS NOT NULL
             OR f.share_change_20d IS NOT NULL
             OR f.share_change_60d IS NOT NULL
          )
          AND NOT EXISTS (
                SELECT 1 FROM mart.etf_flow_daily v
                WHERE v.security_id = f.security_id
                  AND v.trade_date = f.trade_date
                  AND v.calculation_version = 'flow_v2'
          )
        ORDER BY f.trade_date DESC
        LIMIT 10
        """,
    )
    return [
        {
            "dataset": "mart.etf_flow_daily",
            "detail": (
                f"{security_id} {trade_date} 用的仍是 {version}，"
                f"但 {action_date} 有份额折算——机械份额变化会被误读成申赎"
            ),
        }
        for security_id, trade_date, version, action_date in rows
    ]


def _adjusted_version_violations(con) -> list[dict]:
    """复权序列必须有已登记的口径版本。"""
    if not _table_exists(con, "mart.etf_adjusted_daily"):
        return []
    rows = _rows(
        con,
        """
        SELECT security_id, trade_date, calculation_version
        FROM mart.etf_adjusted_daily
        WHERE calculation_version IS NULL OR calculation_version = ''
        LIMIT 10
        """,
    )
    violations = [
        {
            "dataset": "mart.etf_adjusted_daily",
            "detail": f"{security_id} {trade_date} 缺少 calculation_version",
        }
        for security_id, trade_date, _ in rows
    ]

    known = _rows(
        con,
        "SELECT DISTINCT calculation_version FROM mart.etf_adjusted_daily "
        "WHERE calculation_version IS NOT NULL",
    )
    unregistered = sorted({value for (value,) in known if value not in REGISTERED_VERSIONS})
    violations.extend(
        {
            "dataset": "mart.etf_adjusted_daily",
            "detail": f"复权口径 {value} 未在 domain/versions.py 登记",
        }
        for value in unregistered
    )
    return violations[:10]


def _adjusted_future_leak_violations(con) -> list[dict]:
    """复权因子只能用截至当日的公司行为推算。

    重新按"只累积 action_date <= trade_date 的行为"算一遍因子，与落库值比对：
    不一致说明当初用了未来事件（典型是把后复权写成了前复权）。

    范围：只校验**只含份额类行为**的标的。含分红的标的其因子还取决于除息日前
    收盘价，本规则不重算那部分（避免用另一套逻辑给出假阳性）；这部分由
    ``tests/unit/test_adjustment_series.py`` 的用例覆盖。
    """
    if not (
        _table_exists(con, "mart.etf_adjusted_daily")
        and _table_exists(con, "core.etf_corporate_action")
    ):
        return []
    dividend_securities = {
        row[0]
        for row in _rows(
            con,
            "SELECT DISTINCT security_id FROM core.etf_corporate_action "
            "WHERE action_type = 'DIVIDEND'",
        )
    }
    adjusted = _rows(
        con,
        """
        SELECT security_id, trade_date, adjustment_factor
        FROM mart.etf_adjusted_daily
        ORDER BY security_id, trade_date
        """,
    )
    if not adjusted:
        return []

    actions = _rows(
        con,
        """
        SELECT security_id, action_date, share_adjustment_factor
        FROM core.etf_corporate_action
        WHERE share_adjustment_factor IS NOT NULL AND share_adjustment_factor <> 1
        ORDER BY security_id, action_date
        """,
    )
    by_security: dict[str, list[tuple]] = {}
    for security_id, action_date, factor in actions:
        by_security.setdefault(security_id, []).append((action_date, float(factor)))

    violations: list[dict] = []
    for security_id, trade_date, stored in adjusted:
        if security_id in dividend_securities:
            continue
        expected = 1.0
        for action_date, factor in by_security.get(security_id, []):
            if action_date <= trade_date:
                expected *= factor
        if stored is None or abs(float(stored) - expected) > 1e-9:
            violations.append(
                {
                    "dataset": "mart.etf_adjusted_daily",
                    "detail": (
                        f"{security_id} {trade_date} 复权因子 {stored} ≠ "
                        f"按当日可知行为推算的 {expected}"
                    ),
                }
            )
            if len(violations) >= 10:
                break
    return violations


_IMPLEMENTATIONS = {
    "rows_on_non_trading_days": _non_trading_day_violations,
    "orphan_mart_rows": _orphan_mart_violations,
    "estimates_without_version": _estimate_version_violations,
    "mixed_calculation_versions": _mixed_version_violations,
    "zero_substituted_for_unknown": _zero_substitution_violations,
    "missing_source_metadata": _missing_source_metadata_violations,
    "holdings_without_report_date": _holdings_without_report_date,
    "incomplete_market_turnover": _incomplete_turnover_violations,
    "future_data_in_research_snapshot": _future_data_violations,
    "unadjusted_flow_crosses_corporate_action": _flow_crosses_action_violations,
    "adjusted_series_missing_version": _adjusted_version_violations,
    "adjusted_series_future_action_leak": _adjusted_future_leak_violations,
}


def run_data_rules(database_path: Path | None = None) -> list[dict]:
    """执行全部数据规则，返回 ``[{name, severity, description, violations}]``。"""
    path = database_path or settings.database_path
    results: list[dict] = []
    with connect(path) as con:
        for rule in DATA_RULES:
            implementation = _IMPLEMENTATIONS[rule.name]
            violations = implementation(con)
            results.append(
                {
                    "name": rule.name,
                    "severity": rule.severity,
                    "description": rule.description,
                    "violations": violations,
                    "count": len(violations),
                }
            )
    return results
