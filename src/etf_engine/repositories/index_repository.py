from datetime import date

from etf_engine.config.settings import settings
from etf_engine.db.connection import connect
from etf_engine.domain.models import IndexCatalogEntry, IndexConstituent, IndexQuote


class IndexRepository:
    def upsert_catalog(self, entries: list[IndexCatalogEntry]) -> int:
        if not entries:
            return 0
        rows = [
            (
                entry.index_id,
                entry.index_name,
                entry.market_symbol,
                entry.source_meta.source,
                entry.source_meta.fetched_at,
            )
            for entry in entries
        ]
        sql = """
        INSERT INTO core.index_catalog (
            index_id, index_name, market_symbol, source, fetched_at
        ) VALUES (?,?,?,?,?)
        ON CONFLICT (index_id) DO UPDATE SET
            index_name = EXCLUDED.index_name,
            market_symbol = COALESCE(EXCLUDED.market_symbol, core.index_catalog.market_symbol),
            source = EXCLUDED.source,
            fetched_at = EXCLUDED.fetched_at
        """
        with connect(settings.database_path) as con:
            con.executemany(sql, rows)
        return len(rows)

    def catalog(self) -> dict[str, dict]:
        """``{index_id: {index_name, market_symbol}}``。"""
        with connect(settings.database_path) as con:
            rows = con.execute(
                "SELECT index_id, index_name, market_symbol FROM core.index_catalog"
            ).fetchall()
        return {
            index_id: {"index_name": name, "market_symbol": symbol}
            for index_id, name, symbol in rows
        }

    def upsert_map(self, records: list[dict]) -> int:
        """写入 ``core.etf_index_map`` 并同步回 ``core.etf_master`` 的跟踪指数字段。"""
        if not records:
            return 0
        rows = [
            (
                record["etf_id"],
                record["index_id"],
                record.get("index_name"),
                record.get("valid_from"),
                record.get("valid_to"),
                record.get("source", "fund_benchmark"),
            )
            for record in records
        ]
        sql = """
        INSERT INTO core.etf_index_map (
            etf_id, index_id, index_name, valid_from, valid_to, source
        ) VALUES (?,?,?,?,?,?)
        ON CONFLICT (etf_id, index_id, valid_from) DO UPDATE SET
            index_name = EXCLUDED.index_name,
            valid_to = EXCLUDED.valid_to,
            source = EXCLUDED.source
        """
        with connect(settings.database_path) as con:
            con.executemany(sql, rows)
            con.executemany(
                """
                UPDATE core.etf_master
                SET tracking_index_id = ?, tracking_index_name = ?
                WHERE security_id = ?
                """,
                [(r[1], r[2], r[0]) for r in rows],
            )
        return len(rows)

    def tracked_indices(self, limit: int | None = None) -> list[tuple[str, str | None]]:
        """已被 ETF 跟踪的指数 ``[(index_id, market_symbol)]``。"""
        sql = """
        SELECT DISTINCT m.index_id, c.market_symbol
        FROM core.etf_index_map m
        LEFT JOIN core.index_catalog c ON c.index_id = m.index_id
        ORDER BY m.index_id
        """
        values: list = []
        if limit is not None:
            sql += " LIMIT ?"
            values.append(limit)
        with connect(settings.database_path) as con:
            rows = con.execute(sql, values).fetchall()
        return [(row[0], row[1]) for row in rows]

    def set_master_index_name(self, records: list[tuple[str, str]]) -> int:
        """只回填跟踪指数名称（代码未解析出来时也保留名称这一事实）。"""
        if not records:
            return 0
        with connect(settings.database_path) as con:
            con.executemany(
                """
                UPDATE core.etf_master
                SET tracking_index_name = COALESCE(tracking_index_name, ?)
                WHERE security_id = ?
                """,
                [(name, security_id) for security_id, name in records],
            )
        return len(records)

    def upsert_constituents(self, records: list[IndexConstituent]) -> int:
        if not records:
            return 0
        rows = [
            (
                record.index_id,
                record.effective_date,
                record.stock_id,
                record.stock_name,
                float(record.weight_pct) if record.weight_pct is not None else None,
                record.source_meta.source,
                record.source_meta.fetched_at,
            )
            for record in records
        ]
        sql = """
        INSERT INTO core.index_constituent (
            index_id, effective_date, stock_id, stock_name, weight_pct, source, fetched_at
        ) VALUES (?,?,?,?,?,?,?)
        ON CONFLICT (index_id, effective_date, stock_id) DO UPDATE SET
            stock_name = EXCLUDED.stock_name,
            weight_pct = COALESCE(EXCLUDED.weight_pct, core.index_constituent.weight_pct),
            source = EXCLUDED.source,
            fetched_at = EXCLUDED.fetched_at
        """
        with connect(settings.database_path) as con:
            con.executemany(sql, rows)
        return len(rows)

    def upsert_quotes(self, records: list[IndexQuote]) -> int:
        if not records:
            return 0
        rows = [
            (
                record.index_id,
                record.trade_date,
                float(record.open) if record.open is not None else None,
                float(record.high) if record.high is not None else None,
                float(record.low) if record.low is not None else None,
                float(record.close) if record.close is not None else None,
                record.currency,
                record.source_meta.source,
                record.source_meta.fetched_at,
                record.source_meta.quality_status.value,
            )
            for record in records
        ]
        sql = """
        INSERT INTO core.index_quote_daily (
            index_id, trade_date, open, high, low, close, currency,
            source, fetched_at, quality_status
        ) VALUES (?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT (index_id, trade_date) DO UPDATE SET
            open = COALESCE(EXCLUDED.open, core.index_quote_daily.open),
            high = COALESCE(EXCLUDED.high, core.index_quote_daily.high),
            low = COALESCE(EXCLUDED.low, core.index_quote_daily.low),
            close = EXCLUDED.close,
            currency = EXCLUDED.currency,
            source = EXCLUDED.source,
            fetched_at = EXCLUDED.fetched_at,
            quality_status = EXCLUDED.quality_status
        """
        with connect(settings.database_path) as con:
            con.executemany(sql, rows)
        return len(rows)

    def index_ids_with_quotes(self, start_date: date, end_date: date) -> set[str]:
        with connect(settings.database_path) as con:
            rows = con.execute(
                """
                SELECT DISTINCT index_id FROM core.index_quote_daily
                WHERE trade_date BETWEEN ? AND ?
                """,
                [start_date, end_date],
            ).fetchall()
        return {row[0] for row in rows}

    def quote_history(self, index_ids: list[str], limit: int = 1500) -> dict[str, list[dict]]:
        """``{index_id: [{trade_date, close}, ...]}``（按日期升序）。

        位置分位需要长历史，因此这里不做日期过滤，只限制每只指数取最近
        ``limit`` 个观测，避免把整库拉进内存。
        """
        if not index_ids:
            return {}
        sql = """
        SELECT index_id, trade_date, close
        FROM (
            SELECT index_id, trade_date, close,
                   ROW_NUMBER() OVER (PARTITION BY index_id ORDER BY trade_date DESC) AS rn
            FROM core.index_quote_daily
            WHERE index_id IN ({placeholders}) AND close IS NOT NULL
        )
        WHERE rn <= ?
        ORDER BY index_id, trade_date
        """.format(placeholders=",".join("?" for _ in index_ids))
        with connect(settings.database_path) as con:
            rows = con.execute(sql, [*index_ids, limit]).fetchall()
        history: dict[str, list[dict]] = {index_id: [] for index_id in index_ids}
        for index_id, trade_date, close in rows:
            history[index_id].append({"trade_date": trade_date, "close": close})
        return history
