-- pulse_v2：给每层加"原始信号"列，与"确认状态"分开存。
--
-- 背景（实测）：pulse_v1 的阈值偏紧，量能层 250 个交易日里切换了 77 次、
-- 平均只持续 3.2 天——那不是"状态"，是噪音。综合结论因此 3.6 天变一次，
-- 失去了"状态判断器"的意义。
--
-- 规则升级：某一层的原始信号必须**连续 CONFIRM_DAYS=2 个交易日**落在新状态，
-- 才把该层状态切过去；否则维持原状态。综合结论由**确认后的各层**重算。
--
-- 两列都存的价值：
-- * `*_state` 是确认状态，用于状态机与热力图；
-- * `*_raw_state` 是当日原始信号，"原始 ≠ 确认"恰好就是文档要的
--   **边际变化刚出现、还没被确认**的那一刻，界面上单独标出来。

ALTER TABLE mart.market_pulse_daily ADD COLUMN IF NOT EXISTS liquidity_raw_state VARCHAR;
ALTER TABLE mart.market_pulse_daily ADD COLUMN IF NOT EXISTS volume_raw_state VARCHAR;
ALTER TABLE mart.market_pulse_daily ADD COLUMN IF NOT EXISTS etf_raw_state VARCHAR;
