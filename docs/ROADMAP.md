# V1 Roadmap

## Phase 0 — 工程骨架

- [x] Python package
- [x] 配置
- [x] DuckDB migration
- [x] Domain Model
- [x] Source Capability Interface
- [x] CLI / API 基础入口
- [x] 测试骨架

## Phase 1 — 行情底座

- [x] ETF Master Collector
- [x] AKShare ETF Quote Adapter
- [x] ETF Historical Adapter
- [x] Raw Snapshot
- [x] Core Quote Upsert
- [x] Quote Data Quality（按列合并 + `ops.quality_issue` + 交易日校验）

验收：

```text
全市场 ETF 收盘行情可入库
指定 ETF 历史日线可入库
重复执行无重复数据
```

## Phase 2 — 份额与资金

- [x] SSE Share Adapter（显式 `STAT_DATE`，按交易日回补）
- [x] SZSE Share Adapter（快照日期由交易日历推导并留痕）
- [x] Share Snapshot
- [x] NAV（东方财富场内净值，单位净值；最近两个交易日 + 逐只基金历史回补）
- [x] Flow Research（`share_change_*`、`estimated_net_subscription_1d/5d/20d`）
- [x] 历史份额积累（上交所 40 个交易日已回补；深交所只能逐日积累）
- [x] 基金档案补齐（费率/成立日期/管理人/托管人/跟踪标的，沪深同一口径）

验收：

```text
share_change_1d
share_change_5d
share_change_20d
estimated_net_subscription
```

状态：`share_change_1d/5d/20d` 与 `estimated_net_subscription_1d` 已产出；
`estimated_net_subscription_5d/20d` 需要 5/20 个交易日的净值积累（当前净值源只
提供最近两个交易日），随每日运行自动补齐。

## Phase 2.5 — 交易日历（新增）

- [x] `core.trading_calendar` + `etf sync-calendar`
- [x] as-of 解析统一走交易日历（非交易日/未到发布时点回退）
- [x] `nav_source` 跨源标注

## Phase 3 — 指数与持仓

- [x] ETF → Index（基金披露的跟踪标的 → 指数目录精确对齐）
- [x] Index Constituents（中证成分权重）
- [x] Index Weight（成分权重）
- [x] Holdings Disclosure（默认前 20 只，可 `--top-n 0` 覆盖全市场）
- [x] Concentration（Top10 集中度）
- [x] 指数行情（新浪指数日线，仅覆盖新浪在列指数）

## Phase 4 — Research

- [ ] Returns
- [ ] Volatility
- [ ] Drawdown
- [ ] Liquidity
- [ ] Exposure
- [ ] Comparison
- [ ] Screener

## Phase 5 — Application

- [x] `etf show`
- [x] `etf compare`
- [x] `etf screen`
- [x] `etf themes`（主题聚合）
- [x] `/api/v1`
- [x] MCP Tools（8 个工具 + FastMCP transport，SDK 为可选依赖）

## Phase 6 — Production Hardening

- [x] Retry / Backoff（`ingestion/retry.py`，逐标的任务使用指数退避）
- [x] Source Health（`ops.source_health` 记录最近成败与连续失败次数）
- [x] Reconciliation（`reconcile_numeric` 用于同日不同来源的收盘价对账，冲突不覆盖）
- [x] Backups（`data/backups/`，本次基线已备份）
- [x] Scheduler templates（`scripts/run_daily.sh` / `run_weekly.sh` + launchd plist）
- [ ] Live Smoke Tests
- [ ] Data Regression Tests

## Phase 7 — 看盘台（Watchboard）

方案：`docs/WATCHBOARD.md`。把《看盘三件套》的三层框架
（流动性 → 量能 → 宽基 ETF）落到本地数据上。

- [x] 市场层事实表（`core.market_turnover_daily` / `core.margin_balance_daily` /
      `core.market_valuation_daily` / `core.market_activity_daily`）
- [x] 四个市场层能力接口与适配器（SSE/SZSE 每日概况、两融、估值分位、涨跌家数）
- [x] `etf sync-market`（成交额可回补，逐日带超时兜底与退避重试）
- [x] `etf backfill-index-history`（宽基指数长历史 → 位置分位）
- [x] `pulse_v1` 规则引擎（`research/market_pulse.py`，纯函数 + 单测）
- [x] `pulse_v2`：加确认机制（原始信号连续 2 天一致才切换）——v1 实测量能层
      250 天切换 77 次，综合结论 3.6 天变一次；v2 降到 35 / 36 次，并新增
      "原始 ≠ 确认" 的待确认标记与状态切换事件列表
- [x] `mart.market_pulse_daily` / `mart.index_position_daily`
- [x] Watchboard API（`/api/v1/watchboard`）+ 看盘台页面（`/watchboard`）
- [x] 篮子覆盖：`sync-fund-profile --limit 200` + `sync-index-map --limit 200`
      （映射 12 → 241 条，篮子 5 → 38 只；继续扩覆盖仍是 P1）
- [x] 指数 PE 长历史分位（`core.index_valuation_daily` + `mart.index_valuation_daily`，
      覆盖上证50 / 沪深300 / 中证500 / 中证1000；创业板指与科创50 上游没有序列，如实标注）
- [x] MCP 工具 `get_market_pulse`
- [x] 状态历史热力图：`etf backfill-flow`（申赎历史逐日回放）+ `etf backfill-pulse`
      （三层状态逐日回放，250 个交易日），前端 4 行着色网格 + 窗口切换 + 悬停看理由
- [x] 新发基金规模（`core.fund_issuance`，按成立日期聚合成月度规模；
      近 3 个完整月 vs 前 3 个月的环比，实测 -64.6%）
- [x] 资金 vs 量能归一化对比图（两融与成交额各自以窗口首日为 100）
- [x] 篮子净申购累积曲线（按跟踪指数 + 成员覆盖率；缺失日不补 0）
- [ ] 量能分位支持 3 年 / 5 年窗口切换

## Phase 8 — 自检（Audit）

把 `AGENTS.md` 的"不可破坏约束"从文档纪律变成可执行检查（`docs/AUDIT.md`）：

- [x] 架构规则：业务层不得 import 第三方金融库、依赖方向白名单、能力接口齐备（AST 扫描）
- [x] 数据规则 8 条：交易日/孤儿行/估算版本/版本混用/0 顶替缺失/来源标注/持仓披露期/沪深成交额成对
- [x] `etf audit`（`--json` / `--strict` / `--samples`，有 ERROR 时非 0 退出）+ 接入每日链路
- [x] "每条规则都要能被触发"：违规样本测试 + 真实包零违规回归
- [x] 首次运行抓到 `560650.SH` 份额被写成 0 并派生假赎回 → 分层修复（validator + 清理 + 测试）

## 已知缺口（按优先级）

1. **深交所份额历史**：上游只有当前快照（`SHOWTYPE=xlsx` 的基金列表接口不接受日期
   参数，实测传 `txtQueryDate`/`STAT_DATE` 都一样返回当日快照），无法回补，
   只能从现在开始逐日积累。
2. **复权净值**：`unit_nav` / `close` 都是未复权值，跨份额折算的收益、波动率、
   回撤、跟踪误差目前一律返回 NULL（不返回错误值）。要覆盖这些标的，需要采集
   复权净值或前复权收盘价作为独立字段。
3. **上证自编指数缺目录**：`上证科创板芯片指数` 等既不在中证清单也不在新浪列表，
   目录无法给出代码 → 不写 `etf_index_map`，只保留披露的指数名称。
4. **债/商品/海外指数**：中债系列、黄金 AU99.99、恒生/纳斯达克等不在 A 股指数口径内，
   一律记为未匹配，不用近似指数顶替。
5. **上市日期**：`listed_date` 仍只有深交所官方列表提供，沪市 ETF 为 NULL；
   管理人/费率/成立日期已由 `etf sync-fund-profile` 补齐。
6. **持仓披露日**：`core.etf_holding_disclosure.disclosure_date` 上游不提供，保持 NULL。
7. **`tracking_error_60d` 覆盖**：需"指数行情 + 净值"同时具备 40 个对齐交易日，
   且窗口内没有未复权的公司行为。510300 等已可产出（实测 0.53%）；
   扩大覆盖要继续跑 `etf backfill-nav`。
