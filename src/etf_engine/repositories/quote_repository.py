from etf_engine.config.settings import settings
from etf_engine.db.connection import connect
from etf_engine.domain.models import ETFQuote

#: 行情来源（如新浪历史回补）不提供名称时，回落到 master 的简称/全称。
_DISPLAY_NAME = (
    "COALESCE(q.name, "
    "(SELECT COALESCE(m.short_name, m.fund_name) FROM core.etf_master m "
    "WHERE m.security_id = q.security_id))"
)


class QuoteRepository:
    def upsert_many(self, quotes: list[ETFQuote]) -> int:
        if not quotes:
            return 0

        rows = []
        for q in quotes:
            rows.append(
                (
                    q.security_id,
                    q.trade_date,
                    q.name,
                    q.open,
                    q.high,
                    q.low,
                    q.close,
                    q.prev_close,
                    q.change,
                    q.change_pct,
                    q.volume,
                    q.turnover_amount,
                    q.turnover_rate,
                    q.amplitude,
                    q.iopv,
                    q.premium_discount_pct,
                    q.premium_discount_pct_normalized,
                    q.bid1,
                    q.ask1,
                    q.bid1_volume,
                    q.ask1_volume,
                    q.trading_flow_main,
                    q.trading_flow_super_large,
                    q.trading_flow_large,
                    q.trading_flow_medium,
                    q.trading_flow_small,
                    q.source_meta.source,
                    q.source_meta.upstream_source,
                    q.source_meta.fetched_at,
                    q.source_meta.quality_status.value,
                    q.source_meta.ingestion_run_id,
                )
            )

        sql = """
        INSERT INTO core.etf_quote_daily (
            security_id, trade_date, name, open, high, low, close, prev_close,
            change, change_pct, volume, turnover_amount, turnover_rate, amplitude,
            iopv, premium_discount_pct, premium_discount_pct_normalized, bid1, ask1,
            bid1_volume, ask1_volume, trading_flow_main, trading_flow_super_large,
            trading_flow_large, trading_flow_medium, trading_flow_small, source,
            upstream_source, fetched_at, quality_status, ingestion_run_id
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT (security_id, trade_date) DO UPDATE SET
            -- OHLCV 是同一天的事实，后写入的来源可以覆盖（历史回补会修正快照）。
            open = EXCLUDED.open,
            high = EXCLUDED.high,
            low = EXCLUDED.low,
            close = EXCLUDED.close,
            volume = EXCLUDED.volume,
            turnover_amount = EXCLUDED.turnover_amount,
            -- 其余字段按来源能力互补：历史回补没有 iopv/买卖盘/资金流，
            -- 不能把快照已经拿到的值覆盖成 NULL（未知 ≠ 没有）。
            name = COALESCE(EXCLUDED.name, core.etf_quote_daily.name),
            prev_close = COALESCE(EXCLUDED.prev_close, core.etf_quote_daily.prev_close),
            change = COALESCE(EXCLUDED.change, core.etf_quote_daily.change),
            change_pct = COALESCE(EXCLUDED.change_pct, core.etf_quote_daily.change_pct),
            turnover_rate = COALESCE(EXCLUDED.turnover_rate, core.etf_quote_daily.turnover_rate),
            amplitude = COALESCE(EXCLUDED.amplitude, core.etf_quote_daily.amplitude),
            iopv = COALESCE(EXCLUDED.iopv, core.etf_quote_daily.iopv),
            premium_discount_pct = COALESCE(
                EXCLUDED.premium_discount_pct, core.etf_quote_daily.premium_discount_pct
            ),
            premium_discount_pct_normalized = COALESCE(
                EXCLUDED.premium_discount_pct_normalized,
                core.etf_quote_daily.premium_discount_pct_normalized
            ),
            bid1 = COALESCE(EXCLUDED.bid1, core.etf_quote_daily.bid1),
            ask1 = COALESCE(EXCLUDED.ask1, core.etf_quote_daily.ask1),
            bid1_volume = COALESCE(EXCLUDED.bid1_volume, core.etf_quote_daily.bid1_volume),
            ask1_volume = COALESCE(EXCLUDED.ask1_volume, core.etf_quote_daily.ask1_volume),
            trading_flow_main = COALESCE(
                EXCLUDED.trading_flow_main, core.etf_quote_daily.trading_flow_main
            ),
            trading_flow_super_large = COALESCE(
                EXCLUDED.trading_flow_super_large, core.etf_quote_daily.trading_flow_super_large
            ),
            trading_flow_large = COALESCE(
                EXCLUDED.trading_flow_large, core.etf_quote_daily.trading_flow_large
            ),
            trading_flow_medium = COALESCE(
                EXCLUDED.trading_flow_medium, core.etf_quote_daily.trading_flow_medium
            ),
            trading_flow_small = COALESCE(
                EXCLUDED.trading_flow_small, core.etf_quote_daily.trading_flow_small
            ),
            source = COALESCE(EXCLUDED.source, core.etf_quote_daily.source),
            upstream_source = COALESCE(
                EXCLUDED.upstream_source, core.etf_quote_daily.upstream_source
            ),
            fetched_at = EXCLUDED.fetched_at,
            quality_status = EXCLUDED.quality_status,
            ingestion_run_id = COALESCE(
                EXCLUDED.ingestion_run_id, core.etf_quote_daily.ingestion_run_id
            )
        """

        with connect(settings.database_path) as con:
            con.executemany(sql, rows)
        return len(rows)

    def get_latest(self, security_id: str) -> dict | None:
        with connect(settings.database_path) as con:
            row = con.execute(
                """
                SELECT q.* REPLACE (
                    COALESCE(
                        q.name,
                        (SELECT COALESCE(m.short_name, m.fund_name)
                         FROM core.etf_master m WHERE m.security_id = q.security_id)
                    ) AS name
                )
                FROM core.etf_quote_daily q
                WHERE q.security_id = ?
                ORDER BY q.trade_date DESC
                LIMIT 1
                """,
                [security_id],
            ).fetchone()
            if row is None:
                return None
            columns = [d[0] for d in con.description]
            return dict(zip(columns, row, strict=True))

    def search_latest(self, query: str | None = None, limit: int = 20) -> list[dict]:
        """Return the latest locally stored quote for each matching ETF.

        ``name`` 以上游行情中的名称为准，缺失时回落到 ``core.etf_master``：
        历史回补来源（新浪）不提供名称，直接展示会让前端出现"未命名 ETF"。
        """
        filters = "WHERE row_number = 1"
        values: list[str | int] = []
        if query:
            filters += f" AND (q.security_id ILIKE ? OR {_DISPLAY_NAME} ILIKE ?)"
            pattern = f"%{query}%"
            values.extend([pattern, pattern])
        values.append(limit)

        with connect(settings.database_path) as con:
            rows = con.execute(
                f"""
                SELECT q.* EXCLUDE (row_number) REPLACE (
                    {_DISPLAY_NAME} AS name
                )
                FROM (
                    SELECT *, ROW_NUMBER() OVER (
                        PARTITION BY security_id ORDER BY trade_date DESC
                    ) AS row_number
                    FROM core.etf_quote_daily
                ) q
                {filters}
                ORDER BY turnover_amount DESC NULLS LAST, security_id
                LIMIT ?
                """,
                values,
            ).fetchall()
            columns = [description[0] for description in con.description]
            return [dict(zip(columns, row, strict=True)) for row in rows]

    def dashboard_summary(self) -> dict:
        """Return truthful dashboard metadata derived only from local quotes.

        统计口径只覆盖最新交易日：历史实现把 2026-08-13 的快照和 2026-09-11
        的历史行加在一起算"全市场成交额"，同时把 asof_date 标成 09-11。
        """
        with connect(settings.database_path) as con:
            row = con.execute(
                """
                WITH latest_quotes AS (
                    SELECT security_id, trade_date, turnover_amount,
                           ROW_NUMBER() OVER (
                               PARTITION BY security_id ORDER BY trade_date DESC
                           ) AS row_number,
                           MAX(trade_date) OVER () AS asof_date
                    FROM core.etf_quote_daily
                )
                SELECT
                    COUNT(*) FILTER (WHERE trade_date = asof_date) AS etf_count,
                    MAX(trade_date) AS latest_trade_date,
                    SUM(turnover_amount) FILTER (WHERE trade_date = asof_date)
                        AS total_turnover_amount,
                    COUNT(*) FILTER (WHERE trade_date < asof_date) AS stale_etf_count
                FROM latest_quotes
                WHERE row_number = 1
                """
            ).fetchone()
        return {
            "etf_count": row[0],
            "latest_trade_date": row[1],
            "total_turnover_amount": row[2],
            "stale_etf_count": row[3],
        }

    def top_by_turnover(self, limit: int) -> list[str]:
        """按最近一个交易日的成交额挑选关注列表（回补历史/抓取持仓共用）。"""
        with connect(settings.database_path) as con:
            rows = con.execute(
                """
                SELECT security_id
                FROM (
                    SELECT security_id, turnover_amount,
                           ROW_NUMBER() OVER (
                               PARTITION BY security_id ORDER BY trade_date DESC
                           ) AS row_number
                    FROM core.etf_quote_daily
                )
                WHERE row_number = 1
                ORDER BY turnover_amount DESC NULLS LAST
                LIMIT ?
                """,
                [limit],
            ).fetchall()
        return [row[0] for row in rows]

    def all_security_ids(self) -> list[str]:
        """本地有行情的全部 ETF（按成交额降序），用于全市场批处理。"""
        with connect(settings.database_path) as con:
            rows = con.execute(
                """
                SELECT security_id
                FROM (
                    SELECT security_id, turnover_amount,
                           ROW_NUMBER() OVER (
                               PARTITION BY security_id ORDER BY trade_date DESC
                           ) AS row_number
                    FROM core.etf_quote_daily
                )
                WHERE row_number = 1
                ORDER BY turnover_amount DESC NULLS LAST, security_id
                """
            ).fetchall()
        return [row[0] for row in rows]

    def day_closes(
        self, security_ids: list[str], start_date, end_date
    ) -> dict[tuple[str, object], tuple[float | None, str | None]]:
        """按 (security_id, trade_date) 取已入库的收盘价与来源，用于多源对账。"""
        if not security_ids:
            return {}

        placeholders = ",".join(["?"] * len(security_ids))
        with connect(settings.database_path) as con:
            rows = con.execute(
                f"""
                SELECT security_id, trade_date, close, upstream_source
                FROM core.etf_quote_daily
                WHERE security_id IN ({placeholders})
                  AND trade_date BETWEEN ? AND ?
                """,
                [*security_ids, start_date, end_date],
            ).fetchall()
        return {(row[0], row[1]): (row[2], row[3]) for row in rows}
