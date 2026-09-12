CREATE SCHEMA IF NOT EXISTS raw;
CREATE SCHEMA IF NOT EXISTS core;
CREATE SCHEMA IF NOT EXISTS mart;
CREATE SCHEMA IF NOT EXISTS ops;

CREATE TABLE IF NOT EXISTS core.etf_master (
    security_id VARCHAR PRIMARY KEY,
    ticker VARCHAR NOT NULL,
    exchange VARCHAR NOT NULL,
    fund_name VARCHAR,
    short_name VARCHAR,
    fund_type VARCHAR,
    investment_type VARCHAR,
    manager_name VARCHAR,
    custodian_name VARCHAR,
    established_date DATE,
    listed_date DATE,
    tracking_index_id VARCHAR,
    tracking_index_name VARCHAR,
    reported_aum DOUBLE,
    reported_aum_date DATE,
    asset_region VARCHAR,
    base_currency VARCHAR,
    tracking_index_currency VARCHAR,
    is_cross_border BOOLEAN DEFAULT FALSE,
    management_fee_pct DOUBLE,
    custodian_fee_pct DOUBLE,
    status VARCHAR DEFAULT 'ACTIVE',
    source VARCHAR,
    source_updated_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS core.etf_quote_daily (
    security_id VARCHAR NOT NULL,
    trade_date DATE NOT NULL,
    name VARCHAR,
    open DOUBLE,
    high DOUBLE,
    low DOUBLE,
    close DOUBLE,
    prev_close DOUBLE,
    change DOUBLE,
    change_pct DOUBLE,
    volume DOUBLE,
    turnover_amount DOUBLE,
    turnover_rate DOUBLE,
    amplitude DOUBLE,
    iopv DOUBLE,
    premium_discount_pct DOUBLE,
    premium_discount_pct_normalized DOUBLE,
    bid1 DOUBLE,
    ask1 DOUBLE,
    bid1_volume DOUBLE,
    ask1_volume DOUBLE,

    trading_flow_main DOUBLE,
    trading_flow_super_large DOUBLE,
    trading_flow_large DOUBLE,
    trading_flow_medium DOUBLE,
    trading_flow_small DOUBLE,

    source VARCHAR NOT NULL,
    upstream_source VARCHAR,
    fetched_at TIMESTAMP NOT NULL,
    quality_status VARCHAR NOT NULL,
    ingestion_run_id VARCHAR,

    PRIMARY KEY (security_id, trade_date)
);

CREATE TABLE IF NOT EXISTS core.etf_share_daily (
    security_id VARCHAR NOT NULL,
    trade_date DATE NOT NULL,
    fund_name VARCHAR,
    shares DOUBLE NOT NULL,
    nav DOUBLE,
    estimated_aum DOUBLE,
    is_estimated_aum BOOLEAN DEFAULT TRUE,
    source VARCHAR NOT NULL,
    upstream_source VARCHAR,
    fetched_at TIMESTAMP NOT NULL,
    quality_status VARCHAR NOT NULL,
    ingestion_run_id VARCHAR,

    PRIMARY KEY (security_id, trade_date)
);

CREATE TABLE IF NOT EXISTS core.etf_nav_daily (
    security_id VARCHAR NOT NULL,
    nav_date DATE NOT NULL,
    unit_nav DOUBLE,
    adjusted_nav DOUBLE,
    source VARCHAR NOT NULL,
    fetched_at TIMESTAMP NOT NULL,
    quality_status VARCHAR NOT NULL,

    PRIMARY KEY (security_id, nav_date)
);

CREATE TABLE IF NOT EXISTS core.etf_holding_disclosure (
    etf_id VARCHAR NOT NULL,
    report_date DATE NOT NULL,
    disclosure_date DATE,
    stock_id VARCHAR NOT NULL,
    stock_name VARCHAR,
    weight_pct DOUBLE,
    shares DOUBLE,
    market_value DOUBLE,
    source VARCHAR NOT NULL,
    fetched_at TIMESTAMP NOT NULL,

    PRIMARY KEY (etf_id, report_date, stock_id)
);

CREATE TABLE IF NOT EXISTS core.etf_index_map (
    etf_id VARCHAR NOT NULL,
    index_id VARCHAR NOT NULL,
    index_name VARCHAR,
    valid_from DATE,
    valid_to DATE,
    source VARCHAR NOT NULL,
    PRIMARY KEY (etf_id, index_id, valid_from)
);

CREATE TABLE IF NOT EXISTS core.index_constituent (
    index_id VARCHAR NOT NULL,
    effective_date DATE NOT NULL,
    stock_id VARCHAR NOT NULL,
    stock_name VARCHAR,
    weight_pct DOUBLE,
    source VARCHAR NOT NULL,
    fetched_at TIMESTAMP NOT NULL,
    PRIMARY KEY (index_id, effective_date, stock_id)
);

CREATE TABLE IF NOT EXISTS core.etf_tag (
    etf_id VARCHAR NOT NULL,
    tag VARCHAR NOT NULL,
    tag_type VARCHAR NOT NULL,
    confidence DOUBLE,
    source VARCHAR NOT NULL,
    valid_from DATE,
    valid_to DATE,
    PRIMARY KEY (etf_id, tag, tag_type, valid_from)
);

CREATE TABLE IF NOT EXISTS mart.etf_metric_daily (
    security_id VARCHAR NOT NULL,
    trade_date DATE NOT NULL,

    return_1d DOUBLE,
    return_5d DOUBLE,
    return_20d DOUBLE,
    return_60d DOUBLE,

    volatility_20d DOUBLE,
    volatility_60d DOUBLE,

    max_drawdown_60d DOUBLE,
    max_drawdown_250d DOUBLE,
    current_drawdown DOUBLE,

    avg_turnover_5d DOUBLE,
    avg_turnover_20d DOUBLE,
    avg_turnover_60d DOUBLE,
    avg_turnover_amount_5d DOUBLE,
    avg_turnover_amount_20d DOUBLE,
    avg_turnover_amount_60d DOUBLE,

    calculation_version VARCHAR NOT NULL,
    calculated_at TIMESTAMP NOT NULL,

    PRIMARY KEY (security_id, trade_date, calculation_version)
);

CREATE TABLE IF NOT EXISTS mart.etf_flow_daily (
    security_id VARCHAR NOT NULL,
    trade_date DATE NOT NULL,

    share_change_1d DOUBLE,
    share_change_pct_1d DOUBLE,
    share_change_5d DOUBLE,
    share_change_20d DOUBLE,
    share_change_60d DOUBLE,
    share_change_pct_5d DOUBLE,
    share_change_pct_20d DOUBLE,
    share_change_pct_60d DOUBLE,

    estimated_net_subscription_1d DOUBLE,
    estimated_net_subscription_5d DOUBLE,
    estimated_net_subscription_20d DOUBLE,
    estimated_net_subscription_60d DOUBLE,

    consecutive_share_inflow_days INTEGER,
    consecutive_share_outflow_days INTEGER,

    is_estimated BOOLEAN DEFAULT TRUE,
    calculation_version VARCHAR NOT NULL,
    calculated_at TIMESTAMP NOT NULL,

    PRIMARY KEY (security_id, trade_date, calculation_version)
);

CREATE TABLE IF NOT EXISTS ops.ingestion_run (
    run_id VARCHAR PRIMARY KEY,
    dataset VARCHAR NOT NULL,
    source VARCHAR NOT NULL,
    trade_date DATE,
    started_at TIMESTAMP NOT NULL,
    finished_at TIMESTAMP,
    status VARCHAR NOT NULL,
    rows_fetched BIGINT DEFAULT 0,
    rows_written BIGINT DEFAULT 0,
    rows_rejected BIGINT DEFAULT 0,
    error_message VARCHAR
);

CREATE TABLE IF NOT EXISTS ops.source_health (
    source VARCHAR NOT NULL,
    capability VARCHAR NOT NULL,
    status VARCHAR NOT NULL,
    last_success_at TIMESTAMP,
    last_failure_at TIMESTAMP,
    consecutive_failures INTEGER DEFAULT 0,
    last_error VARCHAR,
    PRIMARY KEY (source, capability)
);

CREATE TABLE IF NOT EXISTS ops.quality_issue (
    issue_id VARCHAR PRIMARY KEY,
    dataset VARCHAR NOT NULL,
    security_id VARCHAR,
    trade_date DATE,
    severity VARCHAR NOT NULL,
    rule_name VARCHAR NOT NULL,
    details VARCHAR,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    resolved_at TIMESTAMP
);
