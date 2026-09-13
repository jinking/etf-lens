# V2 总体验收：国产算力 ETF 研究（Point-in-Time）

> 升级方案 §12 的验收 case。所有维度都走 Application Service（与 CLI/API/MCP 同一路径），统一 as-of **2026-09-11**，只使用当天（含）之前的数据。

选题口径：用中证行业分类标签表达国产算力产业链（集成电路 / 半导体材料与设备 / 通信设备），不按 ETF 名称模糊匹配。

> 注意：标签是**前十大持仓穿透**出来的行业暴露，不等于基金的主题定位——宽基 ETF 也可能因为重仓股集中在某行业而带上标签（例如沪深300 带通信设备）。判断主题是否纯粹，请看第 2 节的成分与第 3 节的行业重合度。

## 1. 候选与横向对比

| 代码 | 名称 | 跟踪指数 | 规模 | 20日均成交 | 管理费 | 20日收益 | 当前回撤 | 跟踪误差 | 20日份额变化 | 20日估算净申购 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 510300.SH | 沪深300ETF华泰柏瑞 | 000300 沪深300指数 | 1,071.5亿 | — | 0.15 | — | — | — | — | — |
| 588000.SH | 科创50ETF华夏 | 上证科创板50成份指数 | 919.9亿 | — | 0.15 | — | — | — | — | — |
| 159915.SZ | 创业板ETF易方达 | 399006 创业板指 | 660.8亿 | — | 0.15 | — | — | — | — | — |
| 510310.SH | 沪深300ETF易方达 | 000300 沪深300指数 | 504.7亿 | — | 0.15 | — | — | — | — | — |
| 588200.SH | 科创芯片ETF嘉实 | 上证科创板芯片指数 | 473.4亿 | 29.2亿 | 0.50 | -10.15% | -36.73% | — | 11.2亿 | 12.3亿 |
| 515880.SH | 通信ETF国泰 | 931160 中证全指通信设备指数 | 432.8亿 | 31.6亿 | 0.50 | -2.17% | -41.05% | — | 41.0亿 | 27.9亿 |
| 588080.SH | 科创50ETF易方达 | 上证科创板50成份指数 | 421.9亿 | — | 0.15 | — | — | — | — | — |
| 159516.SZ | 半导体设备ETF国泰 | 931743 中证半导体材料设备主题指数 | 407.5亿 | 32.1亿 | 0.50 | -11.99% | -39.29% | — | — | — |

## 2. 主要成分与行业暴露

**510300.SH 沪深300ETF华泰柏瑞**（标签：通信设备）
- 前五大：中际旭创(4.75%)、宁德时代(3.55%)、新易盛(2.89%)、贵州茅台(2.52%)、兆易创新(1.86%)（报告期 2026-06-30，PIT 置信度 limited）

**588000.SH 科创50ETF华夏**（标签：半导体材料与设备 / 集成电路）
- 前五大：寒武纪(9.3%)、澜起科技(8.13%)、中微公司(8.0%)、海光信息(7.89%)、中芯国际(7.41%)（报告期 2026-06-30，PIT 置信度 limited）

**159915.SZ 创业板ETF易方达**（标签：储能设备 / 通信设备）
- 前五大：中际旭创(14.54%)、宁德时代(13.56%)、新易盛(10.01%)、东方财富(3.45%)、阳光电源(3.1%)（报告期 2026-06-30，PIT 置信度 limited）

**510310.SH 沪深300ETF易方达**（标签：通信设备）
- 前五大：中际旭创(4.88%)、宁德时代(3.6%)、新易盛(2.93%)、贵州茅台(2.56%)、兆易创新(1.89%)（报告期 2026-06-30，PIT 置信度 limited）

**588200.SH 科创芯片ETF嘉实**（标签：半导体材料与设备 / 集成电路）
- 前五大：寒武纪(8.51%)、澜起科技(8.34%)、中微公司(8.25%)、海光信息(8.08%)、中芯国际(7.6%)（报告期 2026-06-30，PIT 置信度 limited）

**515880.SH 通信ETF国泰**（标签：通信设备）
- 前五大：新易盛(15.6%)、中际旭创(14.61%)、工业富联(9.12%)、亨通光电(6.89%)、天孚通信(6.33%)（报告期 2026-06-30，PIT 置信度 limited）

**588080.SH 科创50ETF易方达**（标签：半导体材料与设备 / 集成电路）
- 前五大：寒武纪(9.19%)、澜起科技(8.15%)、中微公司(8.06%)、海光信息(7.9%)、中芯国际(7.42%)（报告期 2026-06-30，PIT 置信度 limited）

**159516.SZ 半导体设备ETF国泰**（标签：半导体材料与设备）
- 前五大：中微公司(15.1%)、北方华创(13.34%)、长川科技(6.46%)、拓荆科技(6.43%)、华海清科(5.49%)（报告期 2026-06-30，PIT 置信度 limited）

## 3. ETF 间持仓重合度

| A | B | 共同持仓 | 重合度 | 加权重合 | Top10 重合 | 行业重合 |
| --- | --- | --- | --- | --- | --- | --- |
| 159516.SZ | 159915.SZ | 1 | 0.10 | 2.13 | 0.10 | 2.13 |
| 159516.SZ | 510300.SH | 0 | 0.00 | 0.00 | 0.00 | 0.00 |
| 159516.SZ | 510310.SH | 1 | 0.10 | 1.31 | 0.10 | 1.31 |
| 159516.SZ | 515880.SH | 0 | 0.00 | 0.00 | 0.00 | 0.00 |
| 159516.SZ | 588000.SH | 2 | 0.20 | 12.03 | 0.20 | 12.03 |
| 159516.SZ | 588080.SH | 2 | 0.20 | 12.29 | 0.20 | 12.29 |
| 159516.SZ | 588200.SH | 2 | 0.20 | 11.86 | 0.20 | 11.86 |
| 159915.SZ | 510300.SH | 3 | 0.30 | 11.19 | 0.30 | 11.19 |
| 159915.SZ | 510310.SH | 3 | 0.30 | 11.41 | 0.30 | 12.72 |
| 159915.SZ | 515880.SH | 3 | 0.30 | 27.04 | 0.30 | 29.23 |
| 159915.SZ | 588000.SH | 0 | 0.00 | 0.00 | 0.00 | 2.13 |
| 159915.SZ | 588080.SH | 0 | 0.00 | 0.00 | 0.00 | 2.13 |
| 159915.SZ | 588200.SH | 0 | 0.00 | 0.00 | 0.00 | 2.13 |
| 510300.SH | 510310.SH | 9 | 0.90 | 21.96 | 0.90 | 21.99 |
| 510300.SH | 515880.SH | 2 | 0.20 | 7.64 | 0.20 | 7.64 |

持仓覆盖（每只 ETF 的持仓条数）：{'510300.SH': 10, '588000.SH': 10, '159915.SZ': 10, '510310.SH': 10, '588200.SH': 10, '515880.SH': 10, '588080.SH': 10, '159516.SZ': 10}

## 4. 同类分位（1.0 = 同类最优）

- **510300.SH** 同类组 index:000300（n=14）：基础规模=100% 流动性=— 跟踪质量=— 成本=33% 资金与拥挤度=11%
- **588000.SH** 同类组 benchmark:上证科创板50成份指数（n=11）：基础规模=100% 流动性=— 跟踪质量=— 成本=60% 资金与拥挤度=100%
- **159915.SZ** 同类组 index:399006（n=6）：基础规模=100% 流动性=— 跟踪质量=— 成本=0% 资金与拥挤度=—
- **510310.SH** 同类组 index:000300（n=14）：基础规模=92% 流动性=— 跟踪质量=— 成本=33% 资金与拥挤度=22%
- **588200.SH** 同类组 benchmark:上证科创板芯片指数（n=7）：基础规模=100% 流动性=— 跟踪质量=— 成本=0% 资金与拥挤度=50%
- **515880.SH** 同类组 index:931160（n=1）：基础规模=— 流动性=— 跟踪质量=— 成本=— 资金与拥挤度=—
- **588080.SH** 同类组 benchmark:上证科创板50成份指数（n=11）：基础规模=90% 流动性=— 跟踪质量=— 成本=60% 资金与拥挤度=90%
- **159516.SZ** 同类组 index:931743（n=5）：基础规模=100% 流动性=— 跟踪质量=— 成本=0% 资金与拥挤度=—

## 5. 数据新鲜度与缺口

- **510300.SH** 研究 as-of=2026-09-11（行情 2026-09-11 · 份额 2026-09-11 · 持仓 2026-06-30）
  - 缺口：avg_turnover_amount_20d=insufficient_history、market_return_20d=insufficient_history、market_return_60d=insufficient_history、max_drawdown_60d=insufficient_history、tracking_index=tracking_index_unavailable、share_change_20d=insufficient_history
- **588000.SH** 研究 as-of=2026-09-11（行情 2026-09-11 · 份额 2026-09-11 · 持仓 2026-06-30）
  - 缺口：avg_turnover_amount_20d=insufficient_history、market_return_20d=insufficient_history、market_return_60d=insufficient_history、max_drawdown_60d=insufficient_history、tracking_index=tracking_index_unavailable、share_change_20d=insufficient_history
- **159915.SZ** 研究 as-of=2026-09-11（行情 2026-09-11 · 份额 2026-09-11 · 持仓 2026-06-30）
  - 缺口：avg_turnover_amount_20d=insufficient_history、market_return_20d=insufficient_history、market_return_60d=insufficient_history、max_drawdown_60d=insufficient_history、tracking_index=tracking_index_unavailable、share_change_20d=insufficient_history
- **510310.SH** 研究 as-of=2026-09-11（行情 2026-09-11 · 份额 2026-09-11 · 持仓 2026-06-30）
  - 缺口：avg_turnover_amount_20d=insufficient_history、market_return_20d=insufficient_history、market_return_60d=insufficient_history、max_drawdown_60d=insufficient_history、tracking_index=tracking_index_unavailable、share_change_20d=insufficient_history
- **588200.SH** 研究 as-of=2026-09-11（行情 2026-09-11 · 份额 2026-09-11 · 持仓 2026-06-30）
  - 缺口：tracking_index=tracking_index_unavailable、tracking_error_60d=tracking_index_unavailable、reported_aum=reported_aum_unavailable
- **515880.SH** 研究 as-of=2026-09-11（行情 2026-09-11 · 份额 2026-09-11 · 持仓 2026-06-30）
  - 缺口：tracking_index=tracking_index_unavailable、tracking_error_60d=tracking_index_unavailable、reported_aum=reported_aum_unavailable
- **588080.SH** 研究 as-of=2026-09-11（行情 2026-09-11 · 份额 2026-09-11 · 持仓 2026-06-30）
  - 缺口：avg_turnover_amount_20d=insufficient_history、market_return_20d=insufficient_history、market_return_60d=insufficient_history、max_drawdown_60d=insufficient_history、tracking_index=tracking_index_unavailable、share_change_20d=insufficient_history
- **159516.SZ** 研究 as-of=2026-09-11（行情 2026-09-11 · 份额 2026-09-11 · 持仓 2026-06-30）
  - 缺口：tracking_index=tracking_index_unavailable、share_change_20d=insufficient_history、share_change_pct_20d=insufficient_history、estimated_net_subscription_20d=insufficient_history_or_nav_unavailable、tracking_error_60d=tracking_index_unavailable、reported_aum=reported_aum_unavailable

## 5.1 PIT 覆盖

| 数据块 | 状态 |
| --- | --- |
| Quote / Share / Metric / Flow | SAFE（按 as-of 截断，口径版本显式指定） |
| Adjusted Series | SAFE（因子只累积 <= 当日的行为） |
| Holdings | LIMITED（只有报告期，无披露日） |
| Tag / Tracking Index | SAFE（有效期过滤；无映射时回落 master 并标注 master_latest） |
| Peer Group | SAFE |
| Fund Profile | LIMITED（profile_observed_at <= asof 才输出费率等字段） |

明细见 `docs/POINT_IN_TIME_COVERAGE.md`。

## 6. 结论边界

- 只输出事实与派生指标，不含任何买卖建议；
- 每个维度都可追到 core.* 的原始来源与 as-of 日期；
- 缺失维度显示为 — 并给出原因（insufficient_history / benchmark_return_basis_unknown 等），不用 0 或近似值顶替；
- 口径版本：复权 adjust_v1、同类分位 peer_v1、市场标准化 market_norm_v1。
