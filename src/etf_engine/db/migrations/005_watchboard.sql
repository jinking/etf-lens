-- 看盘台（Watchboard）市场层事实表。
--
-- 口径声明（不可省略）：本组表的成交额与市值口径是**沪深两市股票**，
-- 不含北交所、不含基金与债券。字段名不写"全市场"，避免口径漂移。
--
-- 单位约定：库内成交额/市值一律为**元**。上交所每日概况给的是亿元，
-- 由适配器换算；原始值进 data/raw/。

-- 交易所每日概况（成交额 / 换手率 / 流通市值），一行一个交易所。
CREATE TABLE IF NOT EXISTS core.market_turnover_daily (
    trade_date DATE NOT NULL,
    exchange VARCHAR NOT NULL,
    turnover_amount DOUBLE,
    --: 交易所口径换手率。深交所每日统计不披露该字段 → NULL，不用别的指标顶替。
    turnover_rate_pct DOUBLE,
    float_market_cap DOUBLE,
    total_market_cap DOUBLE,
    listing_count DOUBLE,
    source VARCHAR NOT NULL,
    upstream_source VARCHAR,
    fetched_at TIMESTAMP NOT NULL,
    quality_status VARCHAR NOT NULL,
    ingestion_run_id VARCHAR,
    PRIMARY KEY (trade_date, exchange)
);

-- 两融余额：沪深分别由两个上游接口提供，分列存储，合计在 mart 里派生。
CREATE TABLE IF NOT EXISTS core.margin_balance_daily (
    trade_date DATE NOT NULL,
    exchange VARCHAR NOT NULL,
    financing_balance DOUBLE,
    financing_buy_amount DOUBLE,
    securities_lending_balance DOUBLE,
    margin_balance DOUBLE,
    source VARCHAR NOT NULL,
    upstream_source VARCHAR,
    fetched_at TIMESTAMP NOT NULL,
    quality_status VARCHAR NOT NULL,
    ingestion_run_id VARCHAR,
    PRIMARY KEY (trade_date, exchange)
);

-- 估值与历史分位。index_id = 'CN_A_ALL' 代表全 A 口径。
-- 分位由上游直接给出（上游自带历史分位），属于事实，不由本系统推导。
CREATE TABLE IF NOT EXISTS core.market_valuation_daily (
    index_id VARCHAR NOT NULL,
    trade_date DATE NOT NULL,
    index_close DOUBLE,
    pe_ttm_median DOUBLE,
    pe_ttm_mean DOUBLE,
    pe_lyr_median DOUBLE,
    pe_lyr_mean DOUBLE,
    quantile_ttm_median_all_history DOUBLE,
    quantile_ttm_median_10y DOUBLE,
    quantile_lyr_median_all_history DOUBLE,
    quantile_lyr_median_10y DOUBLE,
    --: 上游口径标识，避免把不同来源的分位当成同一种东西。
    metric_basis VARCHAR,
    source VARCHAR NOT NULL,
    upstream_source VARCHAR,
    fetched_at TIMESTAMP NOT NULL,
    quality_status VARCHAR NOT NULL,
    ingestion_run_id VARCHAR,
    PRIMARY KEY (index_id, trade_date)
);

-- 市场情绪：涨跌家数、涨跌停家数、活跃度。
CREATE TABLE IF NOT EXISTS core.market_activity_daily (
    trade_date DATE PRIMARY KEY,
    rising_count DOUBLE,
    falling_count DOUBLE,
    flat_count DOUBLE,
    suspended_count DOUBLE,
    limit_up_count DOUBLE,
    limit_down_count DOUBLE,
    real_limit_up_count DOUBLE,
    real_limit_down_count DOUBLE,
    activity_pct DOUBLE,
    --: 上游给出的统计时点（如 15:00:00），用于核对这是哪一场收盘的数据。
    statistic_at TIMESTAMP,
    source VARCHAR NOT NULL,
    upstream_source VARCHAR,
    fetched_at TIMESTAMP NOT NULL,
    quality_status VARCHAR NOT NULL,
    ingestion_run_id VARCHAR
);

-- 指数位置分位：派生自 core.index_quote_daily 的收盘价历史。
CREATE TABLE IF NOT EXISTS mart.index_position_daily (
    index_id VARCHAR NOT NULL,
    trade_date DATE NOT NULL,
    close DOUBLE,
    --: 当前收盘价在窗口内的分位（0~1），窗口不足时为 NULL。
    position_pct_250d DOUBLE,
    position_pct_3y DOUBLE,
    --: 距窗口内最高收盘价的回撤（负数）。
    drawdown_from_250d_peak DOUBLE,
    calculation_version VARCHAR NOT NULL,
    calculated_at TIMESTAMP,
    PRIMARY KEY (index_id, trade_date)
);

-- 三层看盘状态（pulse_v1）。规则见 docs/WATCHBOARD.md 第 2 节。
-- 这里存的是**确定性规则引擎**的输出，不是观点；原始事实全部留在 core.*。
CREATE TABLE IF NOT EXISTS mart.market_pulse_daily (
    trade_date DATE PRIMARY KEY,

    -- 第一层：流动性
    margin_balance_total DOUBLE,
    margin_balance_5d_change_pct DOUBLE,
    margin_balance_position_pct_250d DOUBLE,
    liquidity_state VARCHAR,
    liquidity_score INTEGER,
    liquidity_note VARCHAR,

    -- 第二层：量能
    turnover_amount_total DOUBLE,
    turnover_amount_5d_avg DOUBLE,
    turnover_amount_20d_avg DOUBLE,
    turnover_volume_ratio_5d DOUBLE,
    turnover_amount_position_pct_250d DOUBLE,
    turnover_rate_pct DOUBLE,
    rising_count DOUBLE,
    falling_count DOUBLE,
    limit_up_count DOUBLE,
    limit_down_count DOUBLE,
    volume_state VARCHAR,
    volume_score INTEGER,
    volume_note VARCHAR,

    -- 第三层：宽基 ETF
    broad_etf_basket_size INTEGER,
    broad_etf_net_subscription_5d DOUBLE,
    broad_etf_net_subscription_20d DOUBLE,
    broad_etf_premium_median_pct DOUBLE,
    broad_index_id VARCHAR,
    broad_index_position_pct_250d DOUBLE,
    etf_state VARCHAR,
    etf_score INTEGER,
    etf_note VARCHAR,

    -- 综合
    overall_state VARCHAR,
    overall_strong_layers INTEGER,
    overall_known_layers INTEGER,
    quadrant_label VARCHAR,

    calculation_version VARCHAR NOT NULL,
    calculated_at TIMESTAMP
);
