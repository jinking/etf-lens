ALTER TABLE core.etf_master ADD COLUMN IF NOT EXISTS reported_aum DOUBLE;
ALTER TABLE core.etf_master ADD COLUMN IF NOT EXISTS reported_aum_date DATE;
ALTER TABLE core.etf_master ADD COLUMN IF NOT EXISTS asset_region VARCHAR;
ALTER TABLE core.etf_master ADD COLUMN IF NOT EXISTS base_currency VARCHAR;
ALTER TABLE core.etf_master ADD COLUMN IF NOT EXISTS tracking_index_currency VARCHAR;
ALTER TABLE core.etf_master ADD COLUMN IF NOT EXISTS is_cross_border BOOLEAN DEFAULT FALSE;

ALTER TABLE core.etf_quote_daily ADD COLUMN IF NOT EXISTS premium_discount_pct_normalized DOUBLE;
ALTER TABLE core.etf_quote_daily ADD COLUMN IF NOT EXISTS bid1 DOUBLE;
ALTER TABLE core.etf_quote_daily ADD COLUMN IF NOT EXISTS ask1 DOUBLE;
ALTER TABLE core.etf_quote_daily ADD COLUMN IF NOT EXISTS bid1_volume DOUBLE;
ALTER TABLE core.etf_quote_daily ADD COLUMN IF NOT EXISTS ask1_volume DOUBLE;

ALTER TABLE core.etf_share_daily ADD COLUMN IF NOT EXISTS is_estimated_aum BOOLEAN DEFAULT TRUE;

ALTER TABLE mart.etf_metric_daily ADD COLUMN IF NOT EXISTS avg_turnover_amount_5d DOUBLE;
ALTER TABLE mart.etf_metric_daily ADD COLUMN IF NOT EXISTS avg_turnover_amount_20d DOUBLE;
ALTER TABLE mart.etf_metric_daily ADD COLUMN IF NOT EXISTS avg_turnover_amount_60d DOUBLE;
ALTER TABLE mart.etf_flow_daily ADD COLUMN IF NOT EXISTS share_change_pct_5d DOUBLE;
ALTER TABLE mart.etf_flow_daily ADD COLUMN IF NOT EXISTS share_change_pct_20d DOUBLE;
ALTER TABLE mart.etf_flow_daily ADD COLUMN IF NOT EXISTS share_change_pct_60d DOUBLE;
ALTER TABLE mart.etf_flow_daily ADD COLUMN IF NOT EXISTS estimated_net_subscription_60d DOUBLE;

CREATE TABLE IF NOT EXISTS core.etf_quote_snapshot (
    security_id VARCHAR NOT NULL,
    snapshot_time TIMESTAMP NOT NULL,
    trade_date DATE NOT NULL,
    last_price DOUBLE,
    bid1 DOUBLE,
    ask1 DOUBLE,
    bid1_volume DOUBLE,
    ask1_volume DOUBLE,
    source VARCHAR NOT NULL,
    fetched_at TIMESTAMP NOT NULL,
    quality_status VARCHAR NOT NULL,
    PRIMARY KEY (security_id, snapshot_time)
);

CREATE TABLE IF NOT EXISTS core.index_quote_daily (
    index_id VARCHAR NOT NULL,
    trade_date DATE NOT NULL,
    open DOUBLE,
    high DOUBLE,
    low DOUBLE,
    close DOUBLE,
    currency VARCHAR,
    source VARCHAR NOT NULL,
    fetched_at TIMESTAMP NOT NULL,
    quality_status VARCHAR NOT NULL,
    PRIMARY KEY (index_id, trade_date)
);
