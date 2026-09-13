-- 同类分组（确定性派生）：一只 ETF 只属于一个主分组。
--
-- 分组优先级：同一跟踪指数 → 同一基准身份（指数名）→ 同一主标签（仅兜底）。
-- 禁止按 ETF 名称模糊匹配——那会把"名字像"当成"同类"，是研究结论里最隐蔽的噪音。
CREATE TABLE IF NOT EXISTS mart.etf_peer_group (
    security_id VARCHAR PRIMARY KEY,
    peer_group_id VARCHAR NOT NULL,
    peer_group_kind VARCHAR NOT NULL,
    peer_group_label VARCHAR,
    peer_count INTEGER NOT NULL,
    calculation_version VARCHAR NOT NULL,
    calculated_at TIMESTAMP NOT NULL
);

-- 同类分位（不是综合评分，也不是买卖建议）。
--
-- 所有 *_rank_pct 都已按"越大越好"统一方向：费用与跟踪误差取的是反向分位
-- （数值越低，分位越高）。方向定义写在 research/peer.py 的常量表里。
CREATE TABLE IF NOT EXISTS mart.etf_peer_metric_daily (
    security_id VARCHAR NOT NULL,
    asof_date DATE NOT NULL,
    peer_group_id VARCHAR NOT NULL,
    peer_count INTEGER NOT NULL,
    aum_rank_pct DOUBLE,
    turnover_rank_pct DOUBLE,
    tracking_error_rank_pct DOUBLE,
    fee_rank_pct DOUBLE,
    premium_stability_rank_pct DOUBLE,
    flow_rank_pct DOUBLE,
    calculation_version VARCHAR NOT NULL,
    calculated_at TIMESTAMP NOT NULL,
    PRIMARY KEY (security_id, asof_date, calculation_version)
);
