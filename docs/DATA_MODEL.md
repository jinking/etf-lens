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

## core.etf_corporate_action

```text
security_id + action_date + action_type   PK
split_ratio                # 披露原文，如 "1:2.0000"
nav_adjustment_factor      # 一次行为的净值和机械倍数（0.5）
share_adjustment_factor    # 份额机械倍数（2）
cash_distribution          # 分红：每份派现金额
source / upstream_source / fetched_at / quality_status / ingestion_run_id
```

只装**披露来源**的事实（天天基金分红送配页）。价格跳变检测只能发现异常，
不能创建这里的行——错误一旦被写成事实就会被固化。

## mart.etf_adjusted_daily

```text
security_id + trade_date + calculation_version   PK
adjusted_close / adjusted_nav / adjusted_shares
adjustment_factor          # U(t)，只累积 <= t 的公司行为
calculated_at
```

口径 `adjust_v1`（后复权，Point-in-Time 安全）。原始 `core` 事实字段一律不改，
复权值单独成表。详见 [`CORPORATE_ACTIONS.md`](CORPORATE_ACTIONS.md)。

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

写入方式（两个入口，口径相同、可叠加）：

```text
etf compute-mart       # 日常：每只 ETF 只写"最新一个有观测的交易日"一行
etf backfill-flow      # 回填：按份额历史逐日回放，补齐历史缺口（仅每周跑）
```

回填行与日常行使用同一 `calculation_version=flow_v1`，按
`(security_id, trade_date, calculation_version)` 幂等 upsert；非交易日不入库
（回填时记 `ops.quality_issue`）。**回放行是"用今天存下的事实重算"**，
不是当时的快照。

## 看盘台市场层（`docs/WATCHBOARD.md`）

口径声明：这一组表的成交额与市值是**沪深两市股票**口径，不含北交所、不含基金与债券；
库内金额一律为**元**（上交所概况页的"亿元"由适配器换算，原始值进 `raw`）。

### core.market_turnover_daily

```text
trade_date + exchange PK
turnover_amount        # 成交额（元）
turnover_rate_pct      # 交易所口径换手率；深交所不披露 → NULL
float_market_cap
total_market_cap
listing_count
source / upstream_source / fetched_at / quality_status / ingestion_run_id
```

沪深分列存储（两个交易所两个来源），合计在 mart 里派生，不在适配器里合并。

### core.margin_balance_daily

```text
trade_date + exchange PK     # SSE / SZSE
financing_balance
financing_buy_amount
securities_lending_balance
margin_balance
source / upstream_source / fetched_at / quality_status / ingestion_run_id
```

### core.market_valuation_daily

```text
index_id + trade_date PK     # 全 A 口径为 CN_A_ALL
index_close
pe_ttm_median / pe_ttm_mean / pe_lyr_median / pe_lyr_mean
quantile_ttm_median_all_history / quantile_ttm_median_10y
quantile_lyr_median_all_history / quantile_lyr_median_10y
metric_basis                 # 上游口径标识，禁止跨来源混用分位
source / upstream_source / fetched_at / quality_status / ingestion_run_id
```

分位由上游直接给出，属于事实；本系统不做二次推导。

### core.market_activity_daily

```text
trade_date PK
rising_count / falling_count / flat_count / suspended_count
limit_up_count / limit_down_count / real_limit_up_count / real_limit_down_count
activity_pct
statistic_at                 # 上游统计时点；拿不到就不入库
source / upstream_source / fetched_at / quality_status / ingestion_run_id
```

### core.fund_issuance

新发基金事实（一行一只基金，主键 `fund_code`）：

```text
fund_code PK
fund_name / company / fund_type / subscription_period / manager
raised_shares       # 募集份额，单位「亿元」；上游未披露 → NULL
established_date    # 成立日期：月度规模按它聚合，不按募集起始日
source / upstream_source / fetched_at / quality_status / ingestion_run_id
```

约定：募集份额先空后补很常见，upsert 时不用 NULL 覆盖已有值；
月度聚合在查询侧做（`fund_issuance_monthly`），同时返回"未披露募集份额的支数"，
不吃掉口径缺口。最近 1~2 个月会因尚未录入而偏低，展示时必须标注为不完整月。

### mart.index_position_daily

```text
index_id + trade_date PK
close
position_pct_250d            # 收盘价在窗口内的分位（0~1）
position_pct_3y
drawdown_from_250d_peak      # 距窗口最高收盘价的回撤（负数）
calculation_version          # pulse_v2
calculated_at
```

### mart.market_pulse_daily

三层状态的每日快照，规则见 `docs/WATCHBOARD.md` 第 2 节，版本号 `pulse_v2`：

```text
trade_date PK

第一层：margin_balance_total / _5d_change_pct / _position_pct_250d
        liquidity_state / liquidity_score / liquidity_note
第二层：turnover_amount_total / _5d_avg / _20d_avg / _volume_ratio_5d
        turnover_amount_position_pct_250d / turnover_rate_pct
        rising_count / falling_count / limit_up_count / limit_down_count
        volume_state / volume_score / volume_note
第三层：broad_etf_basket_size / broad_etf_net_subscription_5d / _20d
        broad_etf_premium_median_pct / broad_index_id
        broad_index_position_pct_250d
        etf_state / etf_score / etf_note
综合：  overall_state / overall_strong_layers / overall_known_layers / quadrant_label

pulse_v2 追加的原始信号列（与确认状态成对存在）：

```text
liquidity_raw_state / volume_raw_state / etf_raw_state
```

`*_state` 是**确认状态**（信号连续 CONFIRM_DAYS=2 天才切换），
`*_raw_state` 是**当日原始信号**。两者不一致时，说明"边际变化已经出现、
但还没被确认"——这是界面上单独标记的那一类日子。
        calculation_version / calculated_at
```

约定：状态取值 `STRONG / NEUTRAL / WEAK / UNKNOWN`，综合结论为
`偏多 / 中性观望 / 防守 / 数据不足`；已知层不足两层时不给结论。
这是**确定性规则引擎**的输出，不是观点，原始事实仍全部留在 `core.*`。

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
