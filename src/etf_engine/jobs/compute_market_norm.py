"""市场层标准化指标（``market_norm_v1``）。

输入全部来自既有事实表，不引入新数据源：

```text
core.market_turnover_daily   成交额 / 流通市值 / 上市家数（沪深分列 → 求和）
core.margin_balance_daily    两融余额（沪深分列 → 求和）
core.market_activity_daily   涨跌家数 / 涨跌停家数
```

任一分量缺失时对应字段为 NULL——不做"用另一边交易所顶上"这类近似。
"""

from datetime import date, datetime

from etf_engine.config.settings import settings
from etf_engine.db.connection import connect
from etf_engine.domain.versions import MARKET_NORM_VERSION
from etf_engine.ingestion.run_recorder import IngestionRunRecorder


def _rows(asof: date | None) -> list[tuple]:
    with connect(settings.database_path) as con:
        rows = con.execute(
            """
            WITH turnover AS (
                SELECT trade_date,
                       SUM(turnover_amount) AS turnover_amount,
                       SUM(float_market_cap) AS float_market_cap,
                       SUM(listing_count) AS listing_count,
                       COUNT(DISTINCT exchange) AS exchanges
                FROM core.market_turnover_daily
                WHERE (? IS NULL OR trade_date <= ?)
                GROUP BY trade_date
            ),
            margin AS (
                SELECT trade_date, SUM(margin_balance) AS margin_balance,
                       COUNT(DISTINCT exchange) AS exchanges
                FROM core.margin_balance_daily
                WHERE (? IS NULL OR trade_date <= ?)
                GROUP BY trade_date
            ),
            activity AS (
                SELECT trade_date, rising_count, falling_count, flat_count,
                       limit_up_count
                FROM core.market_activity_daily
                WHERE (? IS NULL OR trade_date <= ?)
            )
            SELECT
                t.trade_date,
                CASE WHEN t.exchanges = 2 AND m.exchanges = 2
                          AND t.float_market_cap > 0
                     THEN m.margin_balance / t.float_market_cap END AS margin_balance_ratio,
                CASE WHEN t.float_market_cap > 0
                     THEN t.turnover_amount / t.float_market_cap END AS turnover_ratio,
                CASE WHEN (a.rising_count + a.falling_count) > 0
                     THEN a.rising_count::DOUBLE / (a.rising_count + a.falling_count) END
                     AS advance_ratio,
                CASE WHEN (a.rising_count + a.falling_count + COALESCE(a.flat_count, 0)) > 0
                     THEN a.limit_up_count::DOUBLE
                          / (a.rising_count + a.falling_count + COALESCE(a.flat_count, 0)) END
                     AS limit_up_ratio,
                t.float_market_cap,
                t.listing_count
            FROM turnover t
            LEFT JOIN margin m ON m.trade_date = t.trade_date
            LEFT JOIN activity a ON a.trade_date = t.trade_date
            ORDER BY t.trade_date
            """,
            [asof, asof, asof, asof, asof, asof],
        ).fetchall()
    return [tuple(row) for row in rows]


def compute_market_norm(asof: date | None = None) -> dict:
    repository_rows = _rows(asof)
    if not repository_rows:
        return {"status": "SKIPPED", "reason": "没有市场层事实"}

    recorder = IngestionRunRecorder()
    run_id = recorder.start("market_norm", "internal_engine", asof)
    calculated_at = datetime.now().astimezone()
    rows = [
        (
            trade_date,
            margin_ratio,
            turnover_ratio,
            advance_ratio,
            limit_up_ratio,
            float_cap,
            listing,
            MARKET_NORM_VERSION,
            calculated_at,
        )
        for (
            trade_date,
            margin_ratio,
            turnover_ratio,
            advance_ratio,
            limit_up_ratio,
            float_cap,
            listing,
        ) in repository_rows
    ]
    sql = """
    INSERT INTO mart.market_norm_daily (
        trade_date, margin_balance_ratio, turnover_ratio, advance_ratio,
        limit_up_ratio, float_market_cap, listing_count,
        calculation_version, calculated_at
    ) VALUES (?,?,?,?,?,?,?,?,?)
    ON CONFLICT (trade_date) DO UPDATE SET
        margin_balance_ratio = EXCLUDED.margin_balance_ratio,
        turnover_ratio = EXCLUDED.turnover_ratio,
        advance_ratio = EXCLUDED.advance_ratio,
        limit_up_ratio = EXCLUDED.limit_up_ratio,
        float_market_cap = EXCLUDED.float_market_cap,
        listing_count = EXCLUDED.listing_count,
        calculation_version = EXCLUDED.calculation_version,
        calculated_at = EXCLUDED.calculated_at
    """
    with connect(settings.database_path) as con:
        con.executemany(sql, rows)

    recorder.finish(
        run_id,
        status="SUCCESS",
        rows_fetched=len(rows),
        rows_written=len(rows),
        rows_rejected=0,
    )
    return {
        "run_id": run_id,
        "rows_written": len(rows),
        "date_range": [rows[0][0].isoformat(), rows[-1][0].isoformat()],
        "with_margin_ratio": sum(1 for row in rows if row[1] is not None),
        "with_activity": sum(1 for row in rows if row[3] is not None),
    }
