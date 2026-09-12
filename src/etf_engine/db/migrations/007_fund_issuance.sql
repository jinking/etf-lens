-- 新发基金（场外增量资金的代理指标）。
--
-- 口径说明：
-- * 一行 = 一只基金，主键是基金代码，重复同步幂等；
-- * `raised_shares` 是**募集份额（亿元）**，上游对部分基金不披露 → NULL；
-- * 上游给的是"成立日期"，因此月度规模要按成立日期聚合，而不是按募集起始日；
-- * 最近 1~2 个月会因为"已成立但尚未录入"而不完整，展示时必须标注。

CREATE TABLE IF NOT EXISTS core.fund_issuance (
    fund_code VARCHAR PRIMARY KEY,
    fund_name VARCHAR,
    company VARCHAR,
    fund_type VARCHAR,
    subscription_period VARCHAR,
    raised_shares DOUBLE,
    established_date DATE,
    manager VARCHAR,
    source VARCHAR NOT NULL,
    upstream_source VARCHAR,
    fetched_at TIMESTAMP NOT NULL,
    quality_status VARCHAR NOT NULL,
    ingestion_run_id VARCHAR
);
