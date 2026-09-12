-- 宽基指数估值（乐咕口径，月度序列，自带长历史）。
--
-- 为什么单独建表：`core.market_valuation_daily` 是**全 A** 口径且上游自带历史分位；
-- 这里是**单条指数**的市盈率序列，分位需要本系统自己算。两者口径不同，
-- 不混在一张表里，也不做跨来源合并。
--
-- 上游没有创业板指 / 科创50 的估值序列：如实记 issue，不用别的指数顶替。

CREATE TABLE IF NOT EXISTS core.index_valuation_daily (
    index_id VARCHAR NOT NULL,
    trade_date DATE NOT NULL,
    --: 上游给的六种口径：加权/等权、静态/滚动、加中位数版本。
    pe_static DOUBLE,
    pe_ttm DOUBLE,
    pe_static_median DOUBLE,
    pe_ttm_median DOUBLE,
    pe_static_equal_weight DOUBLE,
    pe_ttm_equal_weight DOUBLE,
    metric_basis VARCHAR,
    source VARCHAR NOT NULL,
    upstream_source VARCHAR,
    fetched_at TIMESTAMP NOT NULL,
    quality_status VARCHAR NOT NULL,
    ingestion_run_id VARCHAR,
    PRIMARY KEY (index_id, trade_date)
);

-- 估值分位：派生值（本系统在长历史里算），与位置分位分开存，
-- 因为两者的观测频率不同（估值是月度序列，价格是日频）。
CREATE TABLE IF NOT EXISTS mart.index_valuation_daily (
    index_id VARCHAR NOT NULL,
    trade_date DATE NOT NULL,
    pe_ttm DOUBLE,
    --: 当前滚动 PE 在观测窗口内的分位（0~1），样本不足为 NULL。
    pe_ttm_percentile_all_history DOUBLE,
    pe_ttm_percentile_10y DOUBLE,
    observations_all_history INTEGER,
    observations_10y INTEGER,
    calculation_version VARCHAR NOT NULL,
    calculated_at TIMESTAMP,
    PRIMARY KEY (index_id, trade_date)
);
