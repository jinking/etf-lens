# 公司行为与复权序列（V2 Phase 2）

## 1. 要解决的问题

ETF 的份额拆分/折算会让原始序列出现**机械跳变**。实测：

```text
515880.SH  2026-07-03  1:2 份额分拆   单位净值 1.5774 → 0.7885（-50%）
588200.SH  2026-07-20  1:3 份额分拆   单位净值 -67%
```

不处理会造成三类错误结论：

```text
假 -50% 收益 / 假高波动 / 假深回撤
假高跟踪误差（实测算出过 100%）
假巨额申购（Δshares × NAV 把机械翻倍当成买入）
```

V1 的做法是"检测到跳变就拒绝计算"（返回 NULL），正确但会让指标空缺；
V2 补上正确的复权能力。

## 2. 事实从哪来：只信披露，不从跳变推断

```text
来源：天天基金"分红送配"页（基金公司披露口径）
  分红   年份 | 权益登记日 | 除息日 | 每10份分红 | 分红发放日
  拆分   年份 | 拆分折算日 | 拆分类型 | 拆分折算比例
```

纪律：

```text
价格跳变检测只能 "detect anomaly"，不能 "create fact"。
```

一次数据错误（错价、缺行）如果被写成"公司行为事实"，会被固化成永久口径，
再也纠不回来。因此 `core.etf_corporate_action` 只装披露来源的事实；
没有披露来源的标的就保持为空，研究层继续按"不可用"处理。

## 3. 复权口径：后复权（Point-in-Time 安全）

```text
adjusted = 原始值 × U(t)          U(t) 只累积 "action_date <= t" 的行为
```

因子更新——**三套因子独立累计**（V2.1 P0-2 修正）：

```text
                   price_factor   nav_factor   share_factor
拆分/折算 1:k          ×k            ×k            ×k
现金分红 d             ×m            ×m            不变      ← m = P_prev / (P_prev − d)
```

为什么必须拆开：早期实现用**一个** `adjustment_factor` 同时服务净值与份额，
而现金分红也会改变它——分红时实际份额没变，`adjusted_shares` 却出现机械变化，
`flow_v2` 于是把分红日读成一笔**假赎回**。现在份额因子只受拆分/折算影响，
有一条自检规则 `cash_dividend_changes_share_factor` 专门守它。

`adjustment_factor` 列保留但已废弃（值为 `nav_adjustment_factor`），
仅为迁移期兼容旧读者；新代码请用 `nav_adjustment_factor` / `share_adjustment_factor`。

生效日两套对齐（实测确认，不是猜的）：

```text
单位净值 / 份额  折算日 T 当日就是折算后的值
成交价           T 日仍是折算前价格，T+1 个交易日才按新份额交易
```

515880.SH 实测：净值 07-02 的 1.5774 → 07-03 变 0.7885；而价格 07-03 仍是 1.579，
07-06 才是 0.757。两套序列各按自己的生效日对齐，否则会给其中一套制造出假的 ±100% 跳变。

为什么不用前复权：前复权要用**未来**的折算去改历史值。图表上无妨，研究里等于把
当时还不知道的信息灌回历史——正是 `adjusted_series_future_action_leak` 拦的事情。
后复权下，任一历史行只依赖它自己和它之前的事实。

落表 `mart.etf_adjusted_daily`（原始字段一律不动）：

```text
adjusted_close           = close    × price_adjustment_factor(t)
adjusted_nav             = unit_nav × nav_adjustment_factor(t)
adjusted_shares          = shares   ÷ share_adjustment_factor(t)
price_adjustment_factor  = 价格因子（比行为日晚一个交易日生效）
nav_adjustment_factor    = 净值因子（行为日当天生效，含分红乘数）
share_adjustment_factor  = 份额因子（只受拆分/折算影响）
adjustment_factor        = DEPRECATED，等于 nav_adjustment_factor
calculation_version      = adjust_v1
```

## 4. 研究口径升级

```text
metric_v2   收益/波动/回撤改用 adjusted_close；无可靠复权时仍返回 NULL
flow_v2     真实份额变化 = shares(t) − shares(t−1) × k(t)，再 × NAV(t)
            （k(t) = 当日机械倍数；无行为时为 1）
```

`flow_v2` 在**没有公司行为的区间与 v1 完全一致**——它只修正被污染的那部分。
每个 v2 资金流行带 `flow_quality_status`（`clean` / `corporate_action_adjusted`），
版本并存：v1 行保留，不覆盖历史口径。

跟踪差异（`research/tracking.py: tracking_difference`）必须先确定基准口径：

```text
全收益指数 / 净收益指数 / 价格指数 / 未知
```

口径未知 → 返回 NULL + `benchmark_return_basis_unknown`，绝不用价格指数口径
假装算得出来（那会把分红混进"跟踪差异"）。

## 5. 自检

```text
unadjusted_flow_crosses_corporate_action   折算窗口内只有 v1 口径、缺 v2 → ERROR
adjusted_series_missing_version            复权行缺口径版本 / 版本未登记 → ERROR
adjusted_series_future_action_leak         历史行用了未来的折算因子 → ERROR
```

最后一条按"只累积当期可知行为"重算因子并比对落库值，专门拦 Point-in-Time 泄漏。
第一条把 v1 行视为**保留的历史口径**（并存是设计），只在"可读口径里没有 v2"时报警——
那才是"折算后没有重算"的真实故障态。

## 6. 用法

```bash
etf sync-corporate-actions --limit 50     # 逐只取披露（有界、限速）
etf compute-adjusted-series               # 构建复权序列（后复权）
etf compute-mart                          # 同时写 metric_v1/v2 与 flow_v1/v2
```

`scripts/run_daily.sh` 已把前两步排在 `compute-mart` 之前。

## 7. 已知边界

* 披露页只覆盖有分红/折算记录的标的；没有记录的标的因子恒为 1（不为空）。
* 分红复权需要除息日前收盘价：缺失或派现 ≥ 前收盘时不参与复权并记
  `dividend_adjustment_skipped` / `dividend_exceeds_price`，宁可保守。
* 全收益基准暂不给跟踪差异（需要分红序列与基准同日口径），返回
  `total_return_basis_not_supported_yet`。
