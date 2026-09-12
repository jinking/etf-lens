-- 交易日历：TECHNICAL §8 要求同步基于真实交易日历，而不是本地运行日。
CREATE TABLE IF NOT EXISTS core.trading_calendar (
    trade_date DATE PRIMARY KEY,
    source VARCHAR NOT NULL,
    upstream_source VARCHAR,
    fetched_at TIMESTAMP NOT NULL
);

-- 份额行上的净值可能来自独立数据源（上交所规模接口不提供净值），
-- 单独记录来源，避免跨源拼接被误读成单一来源事实。
ALTER TABLE core.etf_share_daily ADD COLUMN IF NOT EXISTS nav_source VARCHAR;

-- 口径统一：turnover 类指标一律使用 avg_turnover_amount_*（成交额口径）。
-- 保留的 avg_turnover_* 是早期文档口径残留，从未被写入过（全为 NULL）；
-- 它们在 calculation_version 之前，DuckDB 不允许带主键索引时直接 DROP，
-- 因此显式标注为废弃，写入口径以 avg_turnover_amount_* 为准。
COMMENT ON COLUMN mart.etf_metric_daily.avg_turnover_5d IS
    'DEPRECATED: 未使用，口径统一为 avg_turnover_amount_5d';
COMMENT ON COLUMN mart.etf_metric_daily.avg_turnover_20d IS
    'DEPRECATED: 未使用，口径统一为 avg_turnover_amount_20d';
COMMENT ON COLUMN mart.etf_metric_daily.avg_turnover_60d IS
    'DEPRECATED: 未使用，口径统一为 avg_turnover_amount_60d';
