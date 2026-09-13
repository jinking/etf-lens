# Benchmark / Peer 相对研究（V2 Phase 3）

把系统从"这只 ETF 表现怎么样"升级成"**相对它该跟踪的指数、以及相对同类 ETF**，表现怎么样"。

## 1. 三类收益，不许混

```text
price_return       二级市场成交价口径
nav_return         基金净值口径（含分红再投资影响的近似）
benchmark_return   基准口径（价格指数 / 全收益 / 净收益 / 未知）
```

基准口径未知时，`tracking_difference` 与同类跟踪质量分位一律为 NULL + 原因
（`benchmark_return_basis_unknown`），绝不用价格指数口径去比含分红的净值。

## 2. 同类分组（确定性，不用名称模糊匹配）

```text
1. 同一 tracking_index_id              （基金披露的跟踪指数，最强依据）
2. 同一 tracking_index_name            （拿不到代码时的等价物）
3. 同一主标签 tag_type='industry'       （仅兜底）
三条都没有 → 不分组
```

分组落在 `mart.etf_peer_group`（一只 ETF 一个主分组），同类样本 < 3 只时**不产分位**——
两三个样本的"同类第一"没有意义。

## 3. 同类分位（不是评分）

`mart.etf_peer_metric_daily`（口径 `peer_v1`）：

```text
aum_rank_pct                 规模
turnover_rank_pct            流动性
tracking_error_rank_pct      跟踪质量
fee_rank_pct                 成本
premium_stability_rank_pct   折溢价稳定性
flow_rank_pct                资金与拥挤度
peer_group_id / peer_count / asof_date / calculation_version
```

分位定义（两个方向共用一把尺子）：

```text
分位 = 比我差的同类只数 / (同类只数 − 1)
最好 → 1.0     最差 → 0.0     并列 → 同分
```

费用与跟踪误差是"数值越低越好"，取反向口径后 **1.0 恒定代表同类最优**，
读的人不必再记方向。

严格不产出：`overall_score = 87`、`BUY/SELL`、任何带权重的综合评分。

## 4. 持仓重合度

`research/overlap.py`，四种口径分开给：

```text
holding_overlap_ratio   共同持仓只数 / 较少一方只数
weighted_overlap        共同持仓上 Σ min(权重A, 权重B)   ← 更接近真实重复敞口
top10_overlap           前十大重合只数 / 10
industry_overlap        行业维度 Σ min(A_行业, B_行业)
```

未分类的持仓计入 `__unclassified__`，不丢样本。

## 5. 用法

```bash
etf peer-metrics --asof 2026-09-11     # 计算分组与分位
etf peer-compare 510300.SH 159919.SZ   # 五个研究维度的同类分位
etf overlap 510300.SH 510310.SH        # 持仓重合度
```

```text
GET  /api/v1/research/peer-compare?security_ids=510300.SH,159919.SZ&asof_date=2026-09-11
GET  /api/v1/research/tracking-quality?security_ids=510300.SH
POST /api/v1/research/overlap      body: ["510300.SH", "510310.SH"]
```

MCP：`compare_peer_etfs`、`get_tracking_quality`、`compare_exposure_overlap`。

Compare 的五个研究维度：

```text
1. 基础规模      2. 流动性      3. 跟踪质量      4. 成本      5. 资金与拥挤度
```

输出形如"AUM：同类 92% 分位"，不给任何买卖建议。

## 6. 已知边界

* 分位依赖同类样本量：宽基指数组样本充足，冷门主题指数可能只有 1–2 只 → 无分位。
* `tracking_error_rank_pct` 需要"跟踪指数行情 + 净值"同时具备 60 日对齐窗口，
  且基准口径可判定为价格指数；否则为 NULL（不是 0）。
* 持仓重合度受持仓覆盖范围限制：目前只有部分 ETF 有披露持仓。
