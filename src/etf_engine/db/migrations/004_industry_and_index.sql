-- 个股行业分类：把"行业"从 services 里的硬编码字典，变成可追溯的数据源事实。
-- 同一只股票可能有多套分类标准，因此标准单独成列，不做跨标准合并。
CREATE TABLE IF NOT EXISTS core.stock_industry (
    stock_id VARCHAR PRIMARY KEY,
    stock_name VARCHAR,
    industry_name VARCHAR NOT NULL,
    industry_code VARCHAR,
    classification_standard VARCHAR,
    source VARCHAR NOT NULL,
    fetched_at TIMESTAMP NOT NULL
);

-- 标签需要标出计算口径与分类覆盖率（估算值必须可追溯）。
ALTER TABLE core.etf_tag ADD COLUMN IF NOT EXISTS calculation_version VARCHAR;
ALTER TABLE core.etf_tag ADD COLUMN IF NOT EXISTS coverage DOUBLE;

-- 指数目录：把指数代码、名称与行情接口需要的符号对齐，供 ETF→指数映射与指数行情使用。
CREATE TABLE IF NOT EXISTS core.index_catalog (
    index_id VARCHAR PRIMARY KEY,
    index_name VARCHAR NOT NULL,
    market_symbol VARCHAR,
    source VARCHAR NOT NULL,
    fetched_at TIMESTAMP NOT NULL
);
