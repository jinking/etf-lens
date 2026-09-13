-- 市场层标准化指标（派生，口径 market_norm_v1）。
--
-- 为什么不直接用绝对水平：两融余额、成交额的绝对量随市场扩容逐年抬升，
-- 拿"绝对水平的历史分位"比不同年份，会把"市场变大了"读成"资金变多了"。
-- 标准化（除以流通市值）才能跨期比较。
CREATE TABLE IF NOT EXISTS mart.market_norm_daily (
    trade_date DATE PRIMARY KEY,
    -- 两融余额 / 流通市值（口径：沪深两市股票，不含北交所与基金债券）
    margin_balance_ratio DOUBLE,
    -- 成交额 / 流通市值（注意：与交易所披露的换手率不是同一个指标）
    turnover_ratio DOUBLE,
    -- 上涨家数 / (上涨 + 下跌)
    advance_ratio DOUBLE,
    -- 涨停家数 / (上涨 + 下跌 + 平盘)
    limit_up_ratio DOUBLE,
    float_market_cap DOUBLE,
    listing_count BIGINT,
    calculation_version VARCHAR NOT NULL,
    calculated_at TIMESTAMP NOT NULL
);
