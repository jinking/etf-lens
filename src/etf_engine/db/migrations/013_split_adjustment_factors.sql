-- 三套复权因子分离（V2.1 P0-2）。
--
-- 背景：原先只有 adjustment_factor 一个因子同时服务 adjusted_nav 与 adjusted_shares，
-- 而现金分红也会改变它 → 分红日 adjusted_shares 出现机械变化 →
-- flow_v2 把分红读成假赎回。这是 correctness bug。
--
-- 规则（见 research/adjustment.py）：
--   拆分/折算   三个因子都乘 k
--   现金分红    price / nav 因子乘 m，**share 因子不变**
ALTER TABLE mart.etf_adjusted_daily ADD COLUMN IF NOT EXISTS nav_adjustment_factor DOUBLE;
ALTER TABLE mart.etf_adjusted_daily ADD COLUMN IF NOT EXISTS share_adjustment_factor DOUBLE;

-- adjustment_factor 保留但已废弃：迁移期兼容旧读者，值等于 nav_adjustment_factor。
-- 不立即删除（历史口径不可静默消失），但新代码不得再用它表示份额。
COMMENT ON COLUMN mart.etf_adjusted_daily.adjustment_factor IS
    'DEPRECATED: 值等于 nav_adjustment_factor，仅为迁移期兼容；份额请用 share_adjustment_factor';
