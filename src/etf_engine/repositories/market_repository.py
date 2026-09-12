"""看盘台市场层的读写（``core.market_*`` / ``mart.market_pulse_daily``）。

写入约定与行情表一致：同一主键 upsert，**不用 NULL 覆盖已有非空值**——
不同上游覆盖的字段不同（如上交所给换手率、深交所不给），
按列合并才不会让后到的来源把先到的事实擦掉。
"""

from datetime import date

from etf_engine.config.settings import settings
from etf_engine.db.connection import connect
from etf_engine.domain.models import (
    FundIssuance,
    IndexValuation,
    MarginBalance,
    MarketActivity,
    MarketTurnover,
    MarketValuation,
)


def _f(value) -> float | None:
    return None if value is None else float(value)


class MarketRepository:
    # ---------------------------------------------------------------- 写入

    def upsert_turnover(
        self, rows: list[MarketTurnover], ingestion_run_id: str | None = None
    ) -> int:
        if not rows:
            return 0
        payload = [
            (
                row.trade_date,
                row.exchange.value,
                _f(row.turnover_amount),
                _f(row.turnover_rate_pct),
                _f(row.float_market_cap),
                _f(row.total_market_cap),
                _f(row.listing_count),
                row.source_meta.source,
                row.source_meta.upstream_source,
                row.source_meta.fetched_at,
                row.source_meta.quality_status.value,
                ingestion_run_id,
            )
            for row in rows
        ]
        sql = """
        INSERT INTO core.market_turnover_daily (
            trade_date, exchange, turnover_amount, turnover_rate_pct,
            float_market_cap, total_market_cap, listing_count,
            source, upstream_source, fetched_at, quality_status, ingestion_run_id
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT (trade_date, exchange) DO UPDATE SET
            turnover_amount = COALESCE(EXCLUDED.turnover_amount,
                                       core.market_turnover_daily.turnover_amount),
            turnover_rate_pct = COALESCE(EXCLUDED.turnover_rate_pct,
                                         core.market_turnover_daily.turnover_rate_pct),
            float_market_cap = COALESCE(EXCLUDED.float_market_cap,
                                        core.market_turnover_daily.float_market_cap),
            total_market_cap = COALESCE(EXCLUDED.total_market_cap,
                                        core.market_turnover_daily.total_market_cap),
            listing_count = COALESCE(EXCLUDED.listing_count,
                                     core.market_turnover_daily.listing_count),
            source = EXCLUDED.source,
            upstream_source = EXCLUDED.upstream_source,
            fetched_at = EXCLUDED.fetched_at,
            quality_status = EXCLUDED.quality_status,
            ingestion_run_id = EXCLUDED.ingestion_run_id
        """
        with connect(settings.database_path) as con:
            con.executemany(sql, payload)
        return len(payload)

    def upsert_margin(self, rows: list[MarginBalance], ingestion_run_id: str | None = None) -> int:
        if not rows:
            return 0
        payload = [
            (
                row.trade_date,
                row.exchange.value,
                _f(row.financing_balance),
                _f(row.financing_buy_amount),
                _f(row.securities_lending_balance),
                _f(row.margin_balance),
                row.source_meta.source,
                row.source_meta.upstream_source,
                row.source_meta.fetched_at,
                row.source_meta.quality_status.value,
                ingestion_run_id,
            )
            for row in rows
        ]
        sql = """
        INSERT INTO core.margin_balance_daily (
            trade_date, exchange, financing_balance, financing_buy_amount,
            securities_lending_balance, margin_balance,
            source, upstream_source, fetched_at, quality_status, ingestion_run_id
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT (trade_date, exchange) DO UPDATE SET
            financing_balance = COALESCE(EXCLUDED.financing_balance,
                                         core.margin_balance_daily.financing_balance),
            financing_buy_amount = COALESCE(EXCLUDED.financing_buy_amount,
                                            core.margin_balance_daily.financing_buy_amount),
            securities_lending_balance = COALESCE(
                EXCLUDED.securities_lending_balance,
                core.margin_balance_daily.securities_lending_balance),
            margin_balance = COALESCE(EXCLUDED.margin_balance,
                                      core.margin_balance_daily.margin_balance),
            source = EXCLUDED.source,
            upstream_source = EXCLUDED.upstream_source,
            fetched_at = EXCLUDED.fetched_at,
            quality_status = EXCLUDED.quality_status,
            ingestion_run_id = EXCLUDED.ingestion_run_id
        """
        with connect(settings.database_path) as con:
            con.executemany(sql, payload)
        return len(payload)

    def upsert_valuation(
        self, rows: list[MarketValuation], ingestion_run_id: str | None = None
    ) -> int:
        if not rows:
            return 0
        payload = [
            (
                row.index_id,
                row.trade_date,
                _f(row.index_close),
                _f(row.pe_ttm_median),
                _f(row.pe_ttm_mean),
                _f(row.pe_lyr_median),
                _f(row.pe_lyr_mean),
                _f(row.quantile_ttm_median_all_history),
                _f(row.quantile_ttm_median_10y),
                _f(row.quantile_lyr_median_all_history),
                _f(row.quantile_lyr_median_10y),
                row.metric_basis,
                row.source_meta.source,
                row.source_meta.upstream_source,
                row.source_meta.fetched_at,
                row.source_meta.quality_status.value,
                ingestion_run_id,
            )
            for row in rows
        ]
        sql = """
        INSERT INTO core.market_valuation_daily (
            index_id, trade_date, index_close,
            pe_ttm_median, pe_ttm_mean, pe_lyr_median, pe_lyr_mean,
            quantile_ttm_median_all_history, quantile_ttm_median_10y,
            quantile_lyr_median_all_history, quantile_lyr_median_10y,
            metric_basis, source, upstream_source, fetched_at, quality_status,
            ingestion_run_id
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT (index_id, trade_date) DO UPDATE SET
            index_close = COALESCE(EXCLUDED.index_close,
                                   core.market_valuation_daily.index_close),
            pe_ttm_median = COALESCE(EXCLUDED.pe_ttm_median,
                                     core.market_valuation_daily.pe_ttm_median),
            pe_ttm_mean = COALESCE(EXCLUDED.pe_ttm_mean,
                                   core.market_valuation_daily.pe_ttm_mean),
            pe_lyr_median = COALESCE(EXCLUDED.pe_lyr_median,
                                     core.market_valuation_daily.pe_lyr_median),
            pe_lyr_mean = COALESCE(EXCLUDED.pe_lyr_mean,
                                   core.market_valuation_daily.pe_lyr_mean),
            quantile_ttm_median_all_history = COALESCE(
                EXCLUDED.quantile_ttm_median_all_history,
                core.market_valuation_daily.quantile_ttm_median_all_history),
            quantile_ttm_median_10y = COALESCE(
                EXCLUDED.quantile_ttm_median_10y,
                core.market_valuation_daily.quantile_ttm_median_10y),
            quantile_lyr_median_all_history = COALESCE(
                EXCLUDED.quantile_lyr_median_all_history,
                core.market_valuation_daily.quantile_lyr_median_all_history),
            quantile_lyr_median_10y = COALESCE(
                EXCLUDED.quantile_lyr_median_10y,
                core.market_valuation_daily.quantile_lyr_median_10y),
            metric_basis = COALESCE(EXCLUDED.metric_basis,
                                    core.market_valuation_daily.metric_basis),
            source = EXCLUDED.source,
            upstream_source = EXCLUDED.upstream_source,
            fetched_at = EXCLUDED.fetched_at,
            quality_status = EXCLUDED.quality_status,
            ingestion_run_id = EXCLUDED.ingestion_run_id
        """
        with connect(settings.database_path) as con:
            con.executemany(sql, payload)
        return len(payload)

    def upsert_activity(
        self, rows: list[MarketActivity], ingestion_run_id: str | None = None
    ) -> int:
        if not rows:
            return 0
        payload = [
            (
                row.trade_date,
                _f(row.rising_count),
                _f(row.falling_count),
                _f(row.flat_count),
                _f(row.suspended_count),
                _f(row.limit_up_count),
                _f(row.limit_down_count),
                _f(row.real_limit_up_count),
                _f(row.real_limit_down_count),
                _f(row.activity_pct),
                row.statistic_at,
                row.source_meta.source,
                row.source_meta.upstream_source,
                row.source_meta.fetched_at,
                row.source_meta.quality_status.value,
                ingestion_run_id,
            )
            for row in rows
        ]
        sql = """
        INSERT INTO core.market_activity_daily (
            trade_date, rising_count, falling_count, flat_count, suspended_count,
            limit_up_count, limit_down_count, real_limit_up_count,
            real_limit_down_count, activity_pct, statistic_at,
            source, upstream_source, fetched_at, quality_status, ingestion_run_id
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT (trade_date) DO UPDATE SET
            rising_count = COALESCE(EXCLUDED.rising_count,
                                    core.market_activity_daily.rising_count),
            falling_count = COALESCE(EXCLUDED.falling_count,
                                     core.market_activity_daily.falling_count),
            flat_count = COALESCE(EXCLUDED.flat_count,
                                  core.market_activity_daily.flat_count),
            suspended_count = COALESCE(EXCLUDED.suspended_count,
                                       core.market_activity_daily.suspended_count),
            limit_up_count = COALESCE(EXCLUDED.limit_up_count,
                                      core.market_activity_daily.limit_up_count),
            limit_down_count = COALESCE(EXCLUDED.limit_down_count,
                                        core.market_activity_daily.limit_down_count),
            real_limit_up_count = COALESCE(EXCLUDED.real_limit_up_count,
                                           core.market_activity_daily.real_limit_up_count),
            real_limit_down_count = COALESCE(
                EXCLUDED.real_limit_down_count,
                core.market_activity_daily.real_limit_down_count),
            activity_pct = COALESCE(EXCLUDED.activity_pct,
                                    core.market_activity_daily.activity_pct),
            statistic_at = COALESCE(EXCLUDED.statistic_at,
                                    core.market_activity_daily.statistic_at),
            source = EXCLUDED.source,
            upstream_source = EXCLUDED.upstream_source,
            fetched_at = EXCLUDED.fetched_at,
            quality_status = EXCLUDED.quality_status,
            ingestion_run_id = EXCLUDED.ingestion_run_id
        """
        with connect(settings.database_path) as con:
            con.executemany(sql, payload)
        return len(payload)

    def upsert_index_valuations(
        self, rows: list[IndexValuation], ingestion_run_id: str | None = None
    ) -> int:
        if not rows:
            return 0
        payload = [
            (
                row.index_id,
                row.trade_date,
                _f(row.pe_static),
                _f(row.pe_ttm),
                _f(row.pe_static_median),
                _f(row.pe_ttm_median),
                _f(row.pe_static_equal_weight),
                _f(row.pe_ttm_equal_weight),
                row.metric_basis,
                row.source_meta.source,
                row.source_meta.upstream_source,
                row.source_meta.fetched_at,
                row.source_meta.quality_status.value,
                ingestion_run_id,
            )
            for row in rows
        ]
        sql = """
        INSERT INTO core.index_valuation_daily (
            index_id, trade_date, pe_static, pe_ttm, pe_static_median,
            pe_ttm_median, pe_static_equal_weight, pe_ttm_equal_weight,
            metric_basis, source, upstream_source, fetched_at, quality_status,
            ingestion_run_id
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT (index_id, trade_date) DO UPDATE SET
            pe_static = COALESCE(EXCLUDED.pe_static,
                                 core.index_valuation_daily.pe_static),
            pe_ttm = COALESCE(EXCLUDED.pe_ttm, core.index_valuation_daily.pe_ttm),
            pe_static_median = COALESCE(EXCLUDED.pe_static_median,
                                        core.index_valuation_daily.pe_static_median),
            pe_ttm_median = COALESCE(EXCLUDED.pe_ttm_median,
                                     core.index_valuation_daily.pe_ttm_median),
            pe_static_equal_weight = COALESCE(
                EXCLUDED.pe_static_equal_weight,
                core.index_valuation_daily.pe_static_equal_weight),
            pe_ttm_equal_weight = COALESCE(
                EXCLUDED.pe_ttm_equal_weight,
                core.index_valuation_daily.pe_ttm_equal_weight),
            metric_basis = COALESCE(EXCLUDED.metric_basis,
                                    core.index_valuation_daily.metric_basis),
            source = EXCLUDED.source,
            upstream_source = EXCLUDED.upstream_source,
            fetched_at = EXCLUDED.fetched_at,
            quality_status = EXCLUDED.quality_status,
            ingestion_run_id = EXCLUDED.ingestion_run_id
        """
        with connect(settings.database_path) as con:
            con.executemany(sql, payload)
        return len(payload)

    def index_valuation_series(self, index_id: str) -> list[dict]:
        """某指数的估值序列（升序），分位计算用。"""
        with connect(settings.database_path) as con:
            rows = con.execute(
                """
                SELECT trade_date, pe_ttm, pe_static
                FROM core.index_valuation_daily
                WHERE index_id = ?
                ORDER BY trade_date
                """,
                [index_id],
            ).fetchall()
        return [{"trade_date": row[0], "pe_ttm": row[1], "pe_static": row[2]} for row in rows]

    def upsert_index_valuation_percentiles(self, rows: list[dict]) -> int:
        if not rows:
            return 0
        sql = """
        INSERT INTO mart.index_valuation_daily (
            index_id, trade_date, pe_ttm, pe_ttm_percentile_all_history,
            pe_ttm_percentile_10y, observations_all_history, observations_10y,
            calculation_version, calculated_at
        ) VALUES (?,?,?,?,?,?,?,?,?)
        ON CONFLICT (index_id, trade_date) DO UPDATE SET
            pe_ttm = EXCLUDED.pe_ttm,
            pe_ttm_percentile_all_history = EXCLUDED.pe_ttm_percentile_all_history,
            pe_ttm_percentile_10y = EXCLUDED.pe_ttm_percentile_10y,
            observations_all_history = EXCLUDED.observations_all_history,
            observations_10y = EXCLUDED.observations_10y,
            calculation_version = EXCLUDED.calculation_version,
            calculated_at = EXCLUDED.calculated_at
        """
        payload = [
            (
                row["index_id"],
                row["trade_date"],
                row["pe_ttm"],
                row["pe_ttm_percentile_all_history"],
                row["pe_ttm_percentile_10y"],
                row["observations_all_history"],
                row["observations_10y"],
                row["calculation_version"],
                row["calculated_at"],
            )
            for row in rows
        ]
        with connect(settings.database_path) as con:
            con.executemany(sql, payload)
        return len(payload)

    def latest_index_valuations(self, index_ids: list[str]) -> list[dict]:
        if not index_ids:
            return []
        placeholders = ",".join("?" for _ in index_ids)
        columns = [
            "index_id",
            "trade_date",
            "pe_ttm",
            "pe_ttm_percentile_all_history",
            "pe_ttm_percentile_10y",
            "observations_all_history",
            "observations_10y",
        ]
        sql = f"""
        SELECT {", ".join(columns)}
        FROM (
            SELECT *, ROW_NUMBER() OVER (PARTITION BY index_id
                                         ORDER BY trade_date DESC) AS rn
            FROM mart.index_valuation_daily
            WHERE index_id IN ({placeholders})
        )
        WHERE rn = 1
        ORDER BY index_id
        """
        with connect(settings.database_path) as con:
            rows = con.execute(sql, index_ids).fetchall()
        return [dict(zip(columns, row, strict=True)) for row in rows]

    def upsert_fund_issuances(
        self, rows: list[FundIssuance], ingestion_run_id: str | None = None
    ) -> int:
        if not rows:
            return 0
        payload = [
            (
                row.fund_code,
                row.fund_name,
                row.company,
                row.fund_type,
                row.subscription_period,
                _f(row.raised_shares),
                row.established_date,
                row.manager,
                row.source_meta.source,
                row.source_meta.upstream_source,
                row.source_meta.fetched_at,
                row.source_meta.quality_status.value,
                ingestion_run_id,
            )
            for row in rows
        ]
        sql = """
        INSERT INTO core.fund_issuance (
            fund_code, fund_name, company, fund_type, subscription_period,
            raised_shares, established_date, manager,
            source, upstream_source, fetched_at, quality_status, ingestion_run_id
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT (fund_code) DO UPDATE SET
            fund_name = COALESCE(EXCLUDED.fund_name, core.fund_issuance.fund_name),
            company = COALESCE(EXCLUDED.company, core.fund_issuance.company),
            fund_type = COALESCE(EXCLUDED.fund_type, core.fund_issuance.fund_type),
            subscription_period = COALESCE(EXCLUDED.subscription_period,
                                           core.fund_issuance.subscription_period),
            -- 募集份额先空后补很常见：不用 NULL 覆盖已有值
            raised_shares = COALESCE(EXCLUDED.raised_shares,
                                     core.fund_issuance.raised_shares),
            established_date = COALESCE(EXCLUDED.established_date,
                                        core.fund_issuance.established_date),
            manager = COALESCE(EXCLUDED.manager, core.fund_issuance.manager),
            source = EXCLUDED.source,
            upstream_source = EXCLUDED.upstream_source,
            fetched_at = EXCLUDED.fetched_at,
            quality_status = EXCLUDED.quality_status,
            ingestion_run_id = EXCLUDED.ingestion_run_id
        """
        with connect(settings.database_path) as con:
            con.executemany(sql, payload)
        return len(payload)

    def fund_issuance_monthly(self, months: int = 18) -> list[dict]:
        """按成立日期聚合的月度新发规模（亿元）。

        同时给出**未披露募集份额的支数**：月度数宁可标"口径不全"，
        也不把缺失当 0 摊进合计。
        """
        sql = """
        SELECT DATE_TRUNC('month', established_date) AS month_start,
               COUNT(*) AS fund_count,
               SUM(raised_shares) AS raised_shares_total,
               COUNT(*) FILTER (WHERE raised_shares IS NULL) AS missing_scale_count
        FROM core.fund_issuance
        WHERE established_date IS NOT NULL
        GROUP BY 1
        ORDER BY 1 DESC
        LIMIT ?
        """
        columns = ["month_start", "fund_count", "raised_shares_total", "missing_scale_count"]
        with connect(settings.database_path) as con:
            rows = con.execute(sql, [months]).fetchall()
        return [dict(zip(columns, row, strict=True)) for row in reversed(rows)]

    def dataset_freshness(self) -> list[dict]:
        """各数据集的最近 as-of 日期。

        界面要能一眼看出"哪块数据是今天的、哪块已经滞后"——数字再漂亮，
        过期就是过期。日期一律取自表里的事实日期，不用运行时间。
        """
        sql = """
        SELECT '市场成交额' AS dataset, MAX(trade_date) FROM core.market_turnover_daily
        UNION ALL SELECT '两融余额', MAX(trade_date) FROM core.margin_balance_daily
        UNION ALL SELECT '涨跌家数', MAX(trade_date) FROM core.market_activity_daily
        UNION ALL SELECT '全 A 估值', MAX(trade_date) FROM core.market_valuation_daily
        UNION ALL SELECT '指数估值', MAX(trade_date) FROM core.index_valuation_daily
        UNION ALL SELECT 'ETF 行情快照', MAX(trade_date) FROM core.etf_quote_daily
        UNION ALL SELECT 'ETF 份额', MAX(trade_date) FROM core.etf_share_daily
        UNION ALL SELECT 'ETF 净值', MAX(nav_date) FROM core.etf_nav_daily
        UNION ALL SELECT '指数行情', MAX(trade_date) FROM core.index_quote_daily
        UNION ALL SELECT '申赎估算', MAX(trade_date) FROM mart.etf_flow_daily
        UNION ALL SELECT '三层状态', MAX(trade_date) FROM mart.market_pulse_daily
        """
        with connect(settings.database_path) as con:
            rows = con.execute(sql).fetchall()
        return [{"dataset": row[0], "asof_date": row[1]} for row in rows]

    # ---------------------------------------------------------------- 读取

    def turnover_series(self, limit: int = 250) -> list[dict]:
        """沪深合计成交额序列（升序），合计在这里派生。"""
        sql = """
        SELECT trade_date,
               SUM(turnover_amount)                      AS turnover_amount_total,
               SUM(float_market_cap)                     AS float_market_cap_total,
               MAX(turnover_rate_pct)                    AS sse_turnover_rate_pct,
               COUNT(*)                                  AS exchange_count
        FROM core.market_turnover_daily
        GROUP BY trade_date
        ORDER BY trade_date DESC
        LIMIT ?
        """
        with connect(settings.database_path) as con:
            rows = con.execute(sql, [limit]).fetchall()
        return [
            {
                "trade_date": row[0],
                "turnover_amount_total": row[1],
                "float_market_cap_total": row[2],
                "turnover_rate_pct": row[3],
                "exchange_count": row[4],
            }
            for row in reversed(rows)
        ]

    def margin_series(self, limit: int = 250) -> list[dict]:
        sql = """
        SELECT trade_date,
               SUM(margin_balance)      AS margin_balance_total,
               SUM(financing_balance)   AS financing_balance_total,
               SUM(securities_lending_balance) AS securities_lending_balance_total,
               COUNT(*)                 AS exchange_count
        FROM core.margin_balance_daily
        GROUP BY trade_date
        ORDER BY trade_date DESC
        LIMIT ?
        """
        with connect(settings.database_path) as con:
            rows = con.execute(sql, [limit]).fetchall()
        return [
            {
                "trade_date": row[0],
                "margin_balance_total": row[1],
                "financing_balance_total": row[2],
                "securities_lending_balance_total": row[3],
                "exchange_count": row[4],
            }
            for row in reversed(rows)
        ]

    def activity_series(self, limit: int = 60) -> list[dict]:
        sql = """
        SELECT trade_date, rising_count, falling_count, flat_count, suspended_count,
               limit_up_count, limit_down_count, real_limit_up_count,
               real_limit_down_count, activity_pct, statistic_at
        FROM core.market_activity_daily
        ORDER BY trade_date DESC
        LIMIT ?
        """
        columns = [
            "trade_date",
            "rising_count",
            "falling_count",
            "flat_count",
            "suspended_count",
            "limit_up_count",
            "limit_down_count",
            "real_limit_up_count",
            "real_limit_down_count",
            "activity_pct",
            "statistic_at",
        ]
        with connect(settings.database_path) as con:
            rows = con.execute(sql, [limit]).fetchall()
        return [dict(zip(columns, row, strict=True)) for row in reversed(rows)]

    def latest_activity(self) -> dict | None:
        series = self.activity_series(limit=1)
        return series[-1] if series else None

    def latest_valuation(self, index_id: str) -> dict | None:
        sql = """
        SELECT trade_date, index_close, pe_ttm_median, pe_lyr_median,
               quantile_ttm_median_all_history, quantile_ttm_median_10y,
               quantile_lyr_median_all_history, quantile_lyr_median_10y,
               metric_basis, source
        FROM core.market_valuation_daily
        WHERE index_id = ?
        ORDER BY trade_date DESC
        LIMIT 1
        """
        columns = [
            "trade_date",
            "index_close",
            "pe_ttm_median",
            "pe_lyr_median",
            "quantile_ttm_median_all_history",
            "quantile_ttm_median_10y",
            "quantile_lyr_median_all_history",
            "quantile_lyr_median_10y",
            "metric_basis",
            "source",
        ]
        with connect(settings.database_path) as con:
            row = con.execute(sql, [index_id]).fetchone()
        return None if row is None else dict(zip(columns, row, strict=True))

    def latest_turnover(self) -> dict | None:
        series = self.turnover_series(limit=1)
        return series[-1] if series else None

    def latest_margin(self) -> dict | None:
        series = self.margin_series(limit=1)
        return series[-1] if series else None

    def index_position(self, index_id: str) -> dict | None:
        sql = """
        SELECT index_id, trade_date, close, position_pct_250d, position_pct_3y,
               drawdown_from_250d_peak, calculation_version
        FROM mart.index_position_daily
        WHERE index_id = ?
        ORDER BY trade_date DESC
        LIMIT 1
        """
        columns = [
            "index_id",
            "trade_date",
            "close",
            "position_pct_250d",
            "position_pct_3y",
            "drawdown_from_250d_peak",
            "calculation_version",
        ]
        with connect(settings.database_path) as con:
            row = con.execute(sql, [index_id]).fetchone()
        return None if row is None else dict(zip(columns, row, strict=True))

    # ------------------------------------------------------- mart 落库与读取

    def upsert_index_positions(self, rows: list[dict]) -> int:
        if not rows:
            return 0
        sql = """
        INSERT INTO mart.index_position_daily (
            index_id, trade_date, close, position_pct_250d, position_pct_3y,
            drawdown_from_250d_peak, calculation_version, calculated_at
        ) VALUES (?,?,?,?,?,?,?,?)
        ON CONFLICT (index_id, trade_date) DO UPDATE SET
            close = EXCLUDED.close,
            position_pct_250d = EXCLUDED.position_pct_250d,
            position_pct_3y = EXCLUDED.position_pct_3y,
            drawdown_from_250d_peak = EXCLUDED.drawdown_from_250d_peak,
            calculation_version = EXCLUDED.calculation_version,
            calculated_at = EXCLUDED.calculated_at
        """
        payload = [
            (
                row["index_id"],
                row["trade_date"],
                row["close"],
                row["position_pct_250d"],
                row["position_pct_3y"],
                row["drawdown_from_250d_peak"],
                row["calculation_version"],
                row["calculated_at"],
            )
            for row in rows
        ]
        with connect(settings.database_path) as con:
            con.executemany(sql, payload)
        return len(payload)

    def upsert_pulse(self, row: dict) -> int:
        columns = [
            "trade_date",
            "margin_balance_total",
            "margin_balance_5d_change_pct",
            "margin_balance_position_pct_250d",
            "liquidity_state",
            "liquidity_raw_state",
            "liquidity_score",
            "liquidity_note",
            "turnover_amount_total",
            "turnover_amount_5d_avg",
            "turnover_amount_20d_avg",
            "turnover_volume_ratio_5d",
            "turnover_amount_position_pct_250d",
            "turnover_rate_pct",
            "rising_count",
            "falling_count",
            "limit_up_count",
            "limit_down_count",
            "volume_state",
            "volume_raw_state",
            "volume_score",
            "volume_note",
            "broad_etf_basket_size",
            "broad_etf_net_subscription_5d",
            "broad_etf_net_subscription_20d",
            "broad_etf_premium_median_pct",
            "broad_index_id",
            "broad_index_position_pct_250d",
            "etf_state",
            "etf_raw_state",
            "etf_score",
            "etf_note",
            "overall_state",
            "overall_strong_layers",
            "overall_known_layers",
            "quadrant_label",
            "calculation_version",
            "calculated_at",
        ]
        placeholders = ",".join("?" for _ in columns)
        updates = ",".join(f"{column} = EXCLUDED.{column}" for column in columns[1:])
        sql = (
            f"INSERT INTO mart.market_pulse_daily ({', '.join(columns)}) "
            f"VALUES ({placeholders}) "
            f"ON CONFLICT (trade_date) DO UPDATE SET {updates}"
        )
        with connect(settings.database_path) as con:
            con.execute(sql, [row[column] for column in columns])
        return 1

    def latest_pulse(self) -> dict | None:
        sql = "SELECT * FROM mart.market_pulse_daily ORDER BY trade_date DESC LIMIT 1"
        with connect(settings.database_path) as con:
            cursor = con.execute(sql)
            columns = [item[0] for item in cursor.description]
            row = cursor.fetchone()
        return None if row is None else dict(zip(columns, row, strict=True))

    def pulse_before(self, trade_date: date) -> dict | None:
        """严格早于给定日期的最近一行（pulse_v2 的确认机制要读上一行）。"""
        sql = (
            "SELECT * FROM mart.market_pulse_daily WHERE trade_date < ?"
            " ORDER BY trade_date DESC LIMIT 1"
        )
        with connect(settings.database_path) as con:
            cursor = con.execute(sql, [trade_date])
            columns = [item[0] for item in cursor.description]
            row = cursor.fetchone()
        return None if row is None else dict(zip(columns, row, strict=True))

    def pulse_history(self, limit: int = 60) -> list[dict]:
        sql = "SELECT * FROM mart.market_pulse_daily ORDER BY trade_date DESC LIMIT ?"
        with connect(settings.database_path) as con:
            cursor = con.execute(sql, [limit])
            columns = [item[0] for item in cursor.description]
            rows = cursor.fetchall()
        return [dict(zip(columns, row, strict=True)) for row in reversed(rows)]

    def pulse_at(self, trade_date: date) -> dict | None:
        sql = "SELECT * FROM mart.market_pulse_daily WHERE trade_date = ?"
        with connect(settings.database_path) as con:
            cursor = con.execute(sql, [trade_date])
            columns = [item[0] for item in cursor.description]
            row = cursor.fetchone()
        return None if row is None else dict(zip(columns, row, strict=True))

    def basket_detail(self, index_ids: list[str], asof: date, limit: int = 100) -> list[dict]:
        """宽基 ETF 篮子明细（一行一只 ETF）。

        篮子成员由 ``core.etf_index_map`` 的跟踪指数决定（事实口径）。
        规模/资金/行情各取各自的最新一行，行内带 ``asof``，不假装是同一天。
        """
        if not index_ids:
            return []
        placeholders = ",".join("?" for _ in index_ids)
        sql = f"""
        WITH members AS (
            SELECT etf_id AS security_id, MIN(index_id) AS index_id
            FROM core.etf_index_map
            WHERE index_id IN ({placeholders})
              AND (valid_to IS NULL OR valid_to >= ?)
            GROUP BY etf_id
        ),
        flow AS (
            SELECT security_id, estimated_net_subscription_5d,
                   estimated_net_subscription_20d, trade_date,
                   ROW_NUMBER() OVER (PARTITION BY security_id
                                      ORDER BY trade_date DESC) AS rn
            FROM mart.etf_flow_daily
        ),
        share AS (
            SELECT security_id, estimated_aum, shares, trade_date,
                   ROW_NUMBER() OVER (PARTITION BY security_id
                                      ORDER BY trade_date DESC) AS rn
            FROM core.etf_share_daily
        ),
        quote AS (
            SELECT security_id, trade_date, close, change_pct, turnover_amount,
                   turnover_rate,
                   -- 只用 normalized：上游"基金折价率"是百分比且正负号相反
                   -- （正 = 折价），与 normalized（正 = 溢价）混用会把方向搞反。
                   premium_discount_pct_normalized AS premium_pct,
                   ROW_NUMBER() OVER (PARTITION BY security_id
                                      ORDER BY trade_date DESC) AS rn
            FROM core.etf_quote_daily
        )
        SELECT mem.security_id, m.short_name, mem.index_id, c.index_name,
               sh.estimated_aum, sh.shares, sh.trade_date AS share_asof,
               f.estimated_net_subscription_5d, f.estimated_net_subscription_20d,
               f.trade_date AS flow_asof,
               q.trade_date AS quote_asof, q.close, q.change_pct,
               q.turnover_amount, q.turnover_rate, q.premium_pct
        FROM members mem
        LEFT JOIN core.etf_master m ON m.security_id = mem.security_id
        LEFT JOIN core.index_catalog c ON c.index_id = mem.index_id
        LEFT JOIN flow f ON f.security_id = mem.security_id AND f.rn = 1
        LEFT JOIN share sh ON sh.security_id = mem.security_id AND sh.rn = 1
        LEFT JOIN quote q ON q.security_id = mem.security_id AND q.rn = 1
        ORDER BY sh.estimated_aum DESC NULLS LAST, mem.security_id
        LIMIT ?
        """
        columns = [
            "security_id",
            "short_name",
            "index_id",
            "index_name",
            "estimated_aum",
            "shares",
            "share_asof",
            "net_subscription_5d",
            "net_subscription_20d",
            "flow_asof",
            "quote_asof",
            "close",
            "change_pct",
            "turnover_amount",
            "turnover_rate",
            "premium_pct",
        ]
        with connect(settings.database_path) as con:
            rows = con.execute(sql, [*index_ids, asof, limit]).fetchall()
        return [dict(zip(columns, row, strict=True)) for row in rows]

    def basket_member_ids(self, index_ids: list[str], asof: date) -> list[str]:
        """篮子成员（按基金披露的跟踪指数取，事实口径）。"""
        if not index_ids:
            return []
        placeholders = ",".join("?" for _ in index_ids)
        sql = f"""
        SELECT DISTINCT etf_id
        FROM core.etf_index_map
        WHERE index_id IN ({placeholders})
          AND (valid_to IS NULL OR valid_to >= ?)
        """
        with connect(settings.database_path) as con:
            rows = con.execute(sql, [*index_ids, asof]).fetchall()
        return [row[0] for row in rows]

    def latest_quote_date(self) -> date | None:
        with connect(settings.database_path) as con:
            row = con.execute("SELECT MAX(trade_date) FROM core.etf_quote_daily").fetchone()
        return None if row is None else row[0]

    def basket_premium_median(self, index_ids: list[str], asof: date) -> float | None:
        """篮子折溢价中位数（只用 normalized：正 = 溢价）。"""
        members = self.basket_member_ids(index_ids, asof)
        if not members:
            return None
        placeholders = ",".join("?" for _ in members)
        sql = f"""
        SELECT MEDIAN(q.premium_discount_pct_normalized)
        FROM core.etf_quote_daily q
        WHERE q.security_id IN ({placeholders}) AND q.trade_date = ?
        """
        with connect(settings.database_path) as con:
            row = con.execute(sql, [*members, asof]).fetchone()
        return None if row is None else row[0]

    def basket_flow_daily(self, index_ids: list[str], asof: date) -> list[dict]:
        """篮子成员的**逐日**净申购合计（按跟踪指数分组）。

        同时返回每行有多少只成员真正贡献了数据：深市 ETF 的份额只有当天快照，
        日度变化要逐日积累，因此早期这些指数的曲线会明显"参与人数少"——
        这个数字必须一起展示，否则会把"参与者少"读成"资金流出减少"。
        """
        if not index_ids:
            return []
        placeholders = ",".join("?" for _ in index_ids)
        sql = f"""
        WITH members AS (
            SELECT DISTINCT etf_id AS security_id, index_id
            FROM core.etf_index_map
            WHERE index_id IN ({placeholders})
              AND (valid_to IS NULL OR valid_to >= ?)
        ),
        member_count AS (
            SELECT index_id, COUNT(*) AS member_count FROM members GROUP BY index_id
        )
        SELECT f.trade_date,
               mem.index_id,
               SUM(f.estimated_net_subscription_1d) AS daily_net_subscription,
               COUNT(*) FILTER (WHERE f.estimated_net_subscription_1d IS NOT NULL)
                   AS contributor_count,
               MAX(mc.member_count) AS member_count
        FROM mart.etf_flow_daily f
        JOIN members mem ON mem.security_id = f.security_id
        JOIN member_count mc ON mc.index_id = mem.index_id
        GROUP BY f.trade_date, mem.index_id
        ORDER BY mem.index_id, f.trade_date
        """
        columns = [
            "trade_date",
            "index_id",
            "daily_net_subscription",
            "contributor_count",
            "member_count",
        ]
        with connect(settings.database_path) as con:
            rows = con.execute(sql, [*index_ids, asof]).fetchall()
        return [dict(zip(columns, row, strict=True)) for row in rows]
