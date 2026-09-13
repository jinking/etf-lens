# Point-in-Time 覆盖矩阵

研究查询必须能回答："这条结论用的是**哪一天**的数据？当时**是否已经知道**？"
下表是各数据集的实际覆盖状态。`SAFE` = 有明确时间字段且查询按 as-of 过滤；
`LIMITED` = 能做 as-of，但时间字段不能完全代表"市场已知"；`LATEST` = 只有当前值。

| 数据集 / 特征 | 时间字段 | PIT-safe | 当前行为 | 要求行为 | 缺失时回退 |
| --- | --- | --- | --- | --- | --- |
| ETF Quote | `trade_date` | SAFE | `<= asof` 取最近一行 | 同左 | 该块置 NULL + `missing` |
| ETF Share | `trade_date` | SAFE | 同上 | 同左 | 同上 |
| ETF NAV | `nav_date` | SAFE | 同上（并与份额按同日对齐） | 同左 | 同上 |
| Metric | `trade_date` + `calculation_version` | SAFE | 显式取 `metric_v2`，`<= asof` | 同左 | 该块 NULL + 原因 |
| Flow | `trade_date` + `calculation_version` | SAFE | 显式取 `flow_v2`，`<= asof` | 同左 | 同上 |
| Adjusted Series | `trade_date` + `adjust_v1` | SAFE | 因子只累积 `<= t` 的行为 | 同左 | 该块 NULL |
| Holdings | `report_date`（+`disclosure_date`） | **LIMITED** | `get_top10_asof`：`report_date <= asof` 且（有披露日时）`disclosure_date <= asof` | 同左；只有报告期时标记 `pit_confidence=limited` | `missing` |
| ETF Tag | `valid_from` / `valid_to` | SAFE | 标签读取与按标签筛选都带有效期过滤 | 同左 | 该标签不可见 |
| Tracking Index | `etf_index_map.valid_from/valid_to` | SAFE（有 map 时） | 映射优先；无映射回落 master 并标 `master_latest` | 同左 | `tracking_index_pit=master_latest` |
| Fund Profile | `profile_observed_at` | **LIMITED** | `profile_observed_at <= asof` 才输出费率等字段 | 同左；NULL 时给 `profile_not_observed_asof` | 字段 NULL |
| Peer Group | `mart.etf_peer_group_daily.asof_date` | SAFE | 取 `asof_date <= requested` 的最近快照 | 同左 | 无快照时回落当前分组并标 `current_fallback` |
| Peer Metrics | `mart.etf_peer_metric_daily.asof_date` | SAFE | `<= asof` 取最近一行 | 同左 | 分位 NULL |
| Industry（个股行业） | 无（当前快照） | **LATEST** | 只存当前分类标准与结果 | 后续接入带日期的分类历史 | 未分类持仓计入 `__unclassified__` |
| Corporate Actions | `action_date` | SAFE | 复权因子只累积 `<= 当日` 的行为 | 同左 | 不参与复权 + 记录问题 |
| Index Constituents | `effective_date` | SAFE | `<= asof` 取最近一期 | 同左 | 空 |
| Market Norm | `trade_date` | SAFE | `<= asof` | 同左 | 字段 NULL |

## 已知边界

1. **Holdings 的 `LIMITED` 是本质限制**：公开持仓是季度披露。报告期（如 2026-06-30）
   结束**不代表**当天市场已经看到这份持仓。我们把 `disclosure_date` 作为优先约束；
   上游不提供披露日时只能标记 `limited`，而不是假装它是实时组合。
2. **Fund Profile 同理**：费率/管理人只有"我们观测到的当前值"，没有历史档案源，
   因此引入 `profile_observed_at`；as-of 早于观测时间时该字段为 NULL。
3. **Industry 分类目前只有当前快照**：`core.stock_industry` 没有有效期字段，
   所以行业标签的历史可追溯性由 `core.etf_tag.valid_from` 承担（标签本身是带日期的），
   个股分类本身若要回放需要另接带日期的分类历史。

## 测试

```text
tests/integration/test_pit_holdings.py   旧披露期 vs 新披露期 + limited 置信度
tests/integration/test_pit_tags.py       标签有效期 + 按标签筛选
tests/integration/test_pit_peer.py       同类分组按日快照
tests/integration/test_pit_profile.py    档案观测时间
tests/integration/test_point_in_time_compare.py  quote/share/metric/flow
```

统一套路：库中放 `T1 旧值` 与 `T2 新值`，查询 `asof ∈ (T1, T2)`，必须得到**旧值**。
