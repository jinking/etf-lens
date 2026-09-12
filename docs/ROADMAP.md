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

- [ ] ETF Master Collector
- [ ] AKShare ETF Quote Adapter
- [ ] ETF Historical Adapter
- [ ] Raw Snapshot
- [ ] Core Quote Upsert
- [ ] Quote Data Quality

验收：

```text
全市场 ETF 收盘行情可入库
指定 ETF 历史日线可入库
重复执行无重复数据
```

## Phase 2 — 份额与资金

- [ ] SSE Share Adapter
- [ ] SZSE Share Adapter
- [ ] Share Snapshot
- [ ] NAV
- [ ] Flow Research
- [ ] 历史份额积累

验收：

```text
share_change_1d
share_change_5d
share_change_20d
estimated_net_subscription
```

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

- [ ] Retry / Backoff
- [ ] Source Health
- [ ] Reconciliation
- [ ] Backups
- [ ] Scheduler templates
- [ ] Live Smoke Tests
- [ ] Data Regression Tests
