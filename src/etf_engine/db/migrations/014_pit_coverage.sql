-- Point-in-Time 覆盖矩阵（V2.1 Phase 4）。

-- 1) 同类分组升级为按日快照。
-- 原表 mart.etf_peer_group 只有 (security_id) 一行 = "今天的同类"，
-- 历史 as-of 查询会拿到现在的分组。新表按 asof_date 保存，旧表保留兼容。
CREATE TABLE IF NOT EXISTS mart.etf_peer_group_daily (
    security_id VARCHAR NOT NULL,
    asof_date DATE NOT NULL,
    peer_group_id VARCHAR NOT NULL,
    peer_group_kind VARCHAR NOT NULL,
    peer_group_label VARCHAR,
    peer_count INTEGER NOT NULL,
    calculation_version VARCHAR NOT NULL,
    calculated_at TIMESTAMP NOT NULL,
    PRIMARY KEY (security_id, asof_date, calculation_version)
);

-- 2) 基金档案的"观测时间"。
-- 费率/管理人/跟踪标的是**当前观测**到的档案；没有历史档案源时不能假装它 PIT-safe。
-- 记录观测时间后，历史查询可以判定 profile_observed_at <= asof，
-- 否则该字段置 NULL 并给 reason=profile_not_observed_asof（宁可缺失，
-- 也不把未来才知道的档案灌进过去）。
ALTER TABLE core.etf_master ADD COLUMN IF NOT EXISTS profile_observed_at TIMESTAMP;
COMMENT ON COLUMN core.etf_master.profile_observed_at IS
    '档案字段（费率/管理人/跟踪标的等）的观测时间；NULL 表示来源未提供观测时间，历史查询应视为不可用';
