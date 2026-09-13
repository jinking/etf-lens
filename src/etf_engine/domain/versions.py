"""计算口径版本登记处。

规则（`AGENTS.md` 第 8 条）：任何公式变化都必须升级 ``calculation_version``，
不得静默修改历史口径。版本字符串散落在各模块里迟早会漏改，
因此统一在这里登记：

- 已生效的版本不要改值，只能新增；
- 历史版本保留，保证旧数据仍可解释；
- ``etf audit`` 会检查派生表里的版本是否在 :data:`REGISTERED_VERSIONS` 内。
"""

# ---------------------------------------------------------------------------
# 已生效（生产口径）
# ---------------------------------------------------------------------------

#: 研究指标：收益 / 波动 / 回撤 / 流动性。
METRIC_VERSION = "metric_v1"
#: ETF 份额变化与估算申赎资金（Δshares × NAV）。
FLOW_VERSION = "flow_v1"
#: 三层看盘状态规则。
PULSE_VERSION = "pulse_v2"
#: 持仓穿透行业标签。
TAG_VERSION = "tag_v1"

# ---------------------------------------------------------------------------
# V2 待启用（先登记，避免上线时临时起名）
# ---------------------------------------------------------------------------

#: 复权序列（adjusted_close / adjusted_nav / adjusted_shares）。
ADJUST_VERSION = "adjust_v1"
#: 公司行为感知的资金流口径。
FLOW_V2_VERSION = "flow_v2"
#: 基于复权序列的研究指标口径。
METRIC_V2_VERSION = "metric_v2"
#: 相对基准（tracking difference 等）。
BENCHMARK_VERSION = "benchmark_v1"
#: 同类分组与分位排名。
PEER_VERSION = "peer_v1"
#: 市场层标准化指标（margin/float、成交额/流通市值、涨跌家数比）。
MARKET_NORM_VERSION = "market_norm_v1"
#: 实验版看盘规则（与 pulse_v2 并行验证，不替换）。
PULSE_V3_EXPERIMENTAL_VERSION = "pulse_v3_experimental"

#: 全部已登记版本。派生表出现表外版本时视为口径漂移。
REGISTERED_VERSIONS: frozenset[str] = frozenset(
    {
        METRIC_VERSION,
        FLOW_VERSION,
        PULSE_VERSION,
        TAG_VERSION,
        ADJUST_VERSION,
        FLOW_V2_VERSION,
        METRIC_V2_VERSION,
        BENCHMARK_VERSION,
        PEER_VERSION,
        MARKET_NORM_VERSION,
        PULSE_V3_EXPERIMENTAL_VERSION,
    }
)

#: 当前生产口径（写库时使用）。
CURRENT_VERSION_BY_DATASET: dict[str, str] = {
    "mart.etf_metric_daily": METRIC_VERSION,
    "mart.etf_flow_daily": FLOW_VERSION,
    "mart.market_pulse_daily": PULSE_VERSION,
    "core.etf_tag": TAG_VERSION,
}
