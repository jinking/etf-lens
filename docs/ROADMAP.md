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

- [ ] ETF → Index
- [ ] Index Constituents
- [ ] Index Weight
- [ ] Holdings Disclosure
- [ ] Concentration

## Phase 4 — Research

- [ ] Returns
- [ ] Volatility
- [ ] Drawdown
- [ ] Liquidity
- [ ] Exposure
- [ ] Comparison
- [ ] Screener

## Phase 5 — Application

- [ ] `etf show`
- [ ] `etf compare`
- [ ] `etf screen`
- [ ] `/api/v1`
- [ ] MCP Tools

## Phase 6 — Production Hardening

- [ ] Retry / Backoff（`tenacity` 已在依赖里但未使用；回补已按单日容错）
- [ ] Source Health（`ops.source_health` 仍是空表）
- [ ] Reconciliation（`reconcile_numeric` 仍是死代码）
- [x] Backups（`data/backups/`，本次基线已备份）
- [ ] Scheduler templates
- [ ] Live Smoke Tests
- [ ] Data Regression Tests

## 已知缺口（按优先级）

1. **净值历史回补**：`estimated_net_subscription_5d/20d` 依赖净值历史，
   目前只能逐日积累；如需即时可用，需要按基金逐个拉取 `fund_etf_fund_info_em`。
2. **深交所份额历史**：上游只有当前快照，无法回补，只能从现在开始积累。
3. **ETF → 指数 / 指数成分 / 跟踪误差**：`core.etf_index_map`、
   `core.index_constituent`、`core.index_quote_daily` 仍为空，对应 Adapter 未实现。
4. **持仓覆盖**：当前只覆盖按成交额排序的前 N 只 ETF（默认 20），
   `core.etf_holding_disclosure.disclosure_date` 为 NULL（上游不提供）。
5. **行业标签**：`services/tagging_service.py` 里的行业映射是硬编码知识，
   既没有 `calculation_version` 也不是数据源事实，后续应迁到独立 Adapter。
6. **沪市档案字段**：管理人/上市日期只有深交所官方来源，沪市 ETF 该部分仍为 NULL。
