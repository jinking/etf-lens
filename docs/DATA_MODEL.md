# Data Model

DuckDB 使用四个 schema：

```text
raw
core
mart
ops
```

## 时间与交易日

所有"今天是不是交易日"的判断必须来自 `core.trading_calendar`（由
`etf sync-calendar` 从权威交易日历同步），禁止用 Monday-Friday 近似。
份额、净值这类收盘后数据以 `ETF_MARKET_DATA_READY_HOUR`（默认 17 点）为界：
早于该时点运行时，as-of 回退到上一个交易日。

## core.trading_calendar

```text
trade_date PK
source
upstream_source
fetched_at
```

## core.etf_master

```text
security_id PK
ticker
exchange
fund_name
short_name
fund_type
investment_type
manager_name
custodian_name
established_date
listed_date
tracking_index_id
tracking_index_name
management_fee_pct
custodian_fee_pct
status
source
source_updated_at
created_at
updated_at
```

## core.etf_quote_daily

唯一键：

```text
security_id + trade_date
```

字段：

```text
open
high
low
close
prev_close
change
change_pct
volume
turnover_amount
turnover_rate
amplitude
iopv
premium_discount_pct

trading_flow_main
trading_flow_super_large
trading_flow_large
trading_flow_medium
trading_flow_small

source
upstream_source
fetched_at
quality_status
ingestion_run_id
```

## core.etf_share_daily

```text
security_id
trade_date
shares
nav
nav_source        # nav 的独立来源；份额接口不提供净值时由净值源补齐
estimated_aum
is_estimated_aum
source
upstream_source
fetched_at
quality_status
ingestion_run_id
```

约定：

- 上海证券交易所的规模接口自带 `STAT_DATE`，`trade_date` 来自上游；
- 深圳证券交易所的基金列表是"当前快照"，没有日期字段，`trade_date` 由交易日历
  推导，并在 `ops.quality_issue` 记录一条 `share_snapshot_date_derived` 留痕；
- `estimated_aum = shares × nav` 是派生值，`is_estimated_aum = true`；
- 历史份额只允许由"自带统计日期"的来源回补（`etf sync-shares --backfill-days N`）。

## core.etf_nav_daily

```text
security_id
nav_date
unit_nav
adjusted_nav
source
fetched_at
quality_status
```

`unit_nav` 来自东方财富场内基金净值接口（一次返回最近两个交易日）。
`adjusted_nav` 保持 NULL：上游提供的"累计净值"与复权净值口径不同，不做事后映射。

注意：`unit_nav` 是未复权值。跨过份额折算/拆分/分红的区间不得直接计算收益或
跟踪误差，研究层会拒绝计算并在 `quality.reasons` 说明原因（见 TECHNICAL §6.1）。

## core.etf_holding_disclosure

```text
etf_id
report_date
disclosure_date
stock_id
stock_name
weight_pct
shares
market_value
source
fetched_at
```

约定：`report_date` 是报告期（由"2026年2季度"解析成 2026-06-30）。
`disclosure_date` 在东方财富持仓接口里并不存在，保持 NULL，不允许用 `report_date`
顶替。持仓标的代码区分市场：A 股 6 位（`.SH` / `.SZ` / `.BJ`），港股 5 位（`.HK`），
不做补零推断。

## core.etf_index_map

```text
etf_id
index_id
index_name
valid_from
valid_to
source
```

约定：`valid_from` 是"系统观测到该跟踪关系"的日期，不是指数生效日。
跟踪关系来自基金概况页披露的"跟踪标的"字段（缺失时退回"业绩比较基准"），
与指数目录做精确名称对齐；对齐不到时不写映射，只把披露的名称写进
`core.etf_master.tracking_index_name`。

## core.index_catalog

```text
index_id PK
index_name
market_symbol     # 指数行情接口需要的符号，如 sh000300
source
fetched_at
```

目录 = 中证指数全量清单 ∪ 新浪指数列表：深证系列与上证自编指数不在中证清单里，
但它们的行情是可得事实，因此并入目录。

`market_symbol` 是新浪行情符号（可选）。没有该符号的指数（如中证自编主题指数）
走中证指数官网日线，实际来源记录在 `core.index_quote_daily.source`。

## core.stock_industry

```text
stock_id PK
stock_name
industry_name
industry_code
classification_standard   # 如"中证行业分类标准"
source
fetched_at
```

行业不是唯一事实：同一只股票在不同分类标准下行业不同，因此标准单独成列，不做合并。
cninfo 是 A 股口径，港股等非 A 股标的记为"来源不适用"。

## core.index_constituent

```text
index_id
effective_date
stock_id
stock_name
weight_pct
source
fetched_at
```

## core.etf_tag

```text
etf_id
tag
tag_type
confidence
coverage              # 分类覆盖率：能归类到行业的持仓权重占比
source
valid_from
valid_to
calculation_version   # 口径版本，当前 tag_v1
```

## mart.etf_metric_daily

```text
security_id
trade_date

return_1d
return_5d
return_20d
return_60d

volatility_20d
volatility_60d

max_drawdown_60d
max_drawdown_250d
current_drawdown

avg_turnover_5d
avg_turnover_20d
avg_turnover_60d

calculation_version
calculated_at
```

口径说明：成交额类指标一律使用 `avg_turnover_amount_5d / 20d / 60d`。
表里保留的 `avg_turnover_5d / 20d / 60d` 是早期文档口径残留，从未写入过，
已在库中标注为 DEPRECATED。

## mart.etf_flow_daily

```text
security_id
trade_date

share_change_1d
share_change_pct_1d
share_change_5d
share_change_20d
share_change_60d

estimated_net_subscription_1d
estimated_net_subscription_5d
estimated_net_subscription_20d

consecutive_share_inflow_days
consecutive_share_outflow_days

is_estimated
calculation_version
calculated_at
```

口径说明：`share_change_*` / `estimated_net_subscription_*` 基于**最近 N 个有观测的
交易日**（上游缺披露的日期不会插值），因此窗口在存在缺口时可能跨越更长自然日。
估算申购资金需要份额与净值按同一天对齐；净值历史不足时返回 NULL，不降级近似。

## ops.ingestion_run

```text
run_id
dataset
source
trade_date
started_at
finished_at
status
rows_fetched
rows_written
rows_rejected
error_message
```

## ops.source_health

```text
source
capability
status
last_success_at
last_failure_at
consecutive_failures
last_error
```

## ops.quality_issue

```text
issue_id
dataset
security_id
trade_date
severity
rule_name
details
created_at
resolved_at
```
