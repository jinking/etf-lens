-- 公司行为（份额拆分/折算/分红）事实表。
--
-- 纪律：这张表只装**披露来源**的事实（基金公司公告、天天基金分红送配页）。
-- 价格跳变检测只能"发现异常"，不能"创建事实"——否则一次数据错误就会被
-- 固化成"公司行为"，再也纠不回来。
CREATE TABLE IF NOT EXISTS core.etf_corporate_action (
    security_id VARCHAR NOT NULL,
    action_date DATE NOT NULL,
    action_type VARCHAR NOT NULL,
    split_ratio VARCHAR,
    nav_adjustment_factor DOUBLE,
    share_adjustment_factor DOUBLE,
    cash_distribution DOUBLE,
    source VARCHAR NOT NULL,
    upstream_source VARCHAR,
    fetched_at TIMESTAMP NOT NULL,
    quality_status VARCHAR NOT NULL,
    ingestion_run_id VARCHAR,
    PRIMARY KEY (security_id, action_date, action_type)
);

-- 复权序列（派生）。原始事实字段不动，复权值单独成表。
--
-- 口径是**后复权**：adjustment_factor = U(t) 只累积"截至 t 的公司行为"，
-- 因此历史时点的取值不依赖未来事件（Point-in-Time 安全）。
-- 前复权需要未来事件，会把当时还不知道的信息灌回历史，故不采用。
CREATE TABLE IF NOT EXISTS mart.etf_adjusted_daily (
    security_id VARCHAR NOT NULL,
    trade_date DATE NOT NULL,
    adjusted_close DOUBLE,
    adjusted_nav DOUBLE,
    adjusted_shares DOUBLE,
    adjustment_factor DOUBLE NOT NULL,
    calculation_version VARCHAR NOT NULL,
    calculated_at TIMESTAMP NOT NULL,
    PRIMARY KEY (security_id, trade_date, calculation_version)
);

-- 资金流口径升级到 v2 后，需要标注"这一行是否做过公司行为调整"。
ALTER TABLE mart.etf_flow_daily ADD COLUMN IF NOT EXISTS flow_quality_status VARCHAR;

-- 价格与基金层面事实的生效日不同（价格 T+1、净值/份额 T），因此两套因子分开存：
--   adjusted_close = close      × price_adjustment_factor
--   adjusted_nav   = unit_nav   × adjustment_factor
--   adjusted_shares = shares    ÷ adjustment_factor
ALTER TABLE mart.etf_adjusted_daily ADD COLUMN IF NOT EXISTS price_adjustment_factor DOUBLE;
