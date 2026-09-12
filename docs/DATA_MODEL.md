# Data Model

DuckDB 使用四个 schema：

```text
raw
core
mart
ops
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
estimated_aum
source
upstream_source
fetched_at
quality_status
ingestion_run_id
```

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

## core.etf_index_map

```text
etf_id
index_id
index_name
valid_from
valid_to
source
```

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
source
valid_from
valid_to
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
