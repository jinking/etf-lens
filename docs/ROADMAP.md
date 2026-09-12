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
- [x] NAV（东方财富场内净值，单位净值；最近两个交易日）
- [x] Flow Research（`share_change_*`、`estimated_net_subscription_1d`）
- [x] 历史份额积累（上交所 40 个交易日已回补；深交所只能逐日积累）

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
- [ ] Scheduler templates
- [ ] Live Smoke Tests
- [ ] Data Regression Tests

## 已知缺口（按优先级）

1. **深交所份额历史**：上游只有当前快照（`SHOWTYPE=xlsx` 的基金列表接口不接受日期
   参数，实测传 `txtQueryDate`/`STAT_DATE` 都一样返回当日快照），无法回补，
   只能从现在开始逐日积累。
2. **指数行情覆盖**：新浪只收录 562 条指数，中证自编主题指数（如 931160）没有行情符号；
   东方财富的指数行情接口在本机网络被拒（`RemoteDisconnected`），因此这些指数
   `core.index_quote_daily` 为空，跟踪误差不可用，已记 `index_quote_source_missing`。
3. **上证自编指数缺目录**：`上证科创板芯片指数` 等既不在中证清单也不在新浪列表，
   目录无法给出代码 → 不写 `etf_index_map`，只保留披露的指数名称。
4. **债/商品/海外指数**：中债系列、黄金 AU99.99、恒生/纳斯达克等不在 A 股指数口径内，
   一律记为未匹配，不用近似指数顶替。
5. **沪市档案字段**：管理人/上市日期只有深交所官方来源，沪市 ETF 该部分仍为 NULL。
6. **持仓披露日**：`core.etf_holding_disclosure.disclosure_date` 上游不提供，保持 NULL。
7. **`tracking_error_60d`**：需要"指数行情 + 净值"同时具备 40 个对齐交易日；
   指数行情已有 90 个交易日，净值需通过 `etf backfill-nav` 补齐后才会产出。
