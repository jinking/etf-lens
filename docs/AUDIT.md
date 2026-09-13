# 自检（`etf audit`）：把 AGENTS.md 的约束变成可执行检查

## 为什么要有它

`AGENTS.md` 列了一组"不可破坏"的规则：业务层不许直接调第三方金融库、
缺失值用 NULL 而不是 0、估算值必须带口径版本、持仓必须带披露期、日期必须是交易日……
这些规则此前**只写在文档里**，靠人和 Agent 自觉。

这个项目恰恰是给人和 Agent 一起改的，改动频率高——文档纪律没有执行体，
迟早会被某次"顺手重构"悄悄破掉。`etf audit` 就是这些纪律的执行体：

```bash
etf audit            # 人类可读报告；有 ERROR 时退出码非 0
etf audit --json     # 结构化输出，给 Agent / CI / 看板消费
etf audit --strict   # WARN 也算失败
etf audit --samples 10
```

它已经挂在每日链路末尾（`scripts/run_daily.sh`），所以数据一旦破规矩会在当天暴露。

## 检查项

### 架构规则（静态 AST 扫描，不联网）

| 规则 | 内容 |
| --- | --- |
| `no_third_party_finance_in_business_layers` | `services/research/jobs/api/cli/mcp` 不得 import `akshare` / `tushare` / `efinance` / `baostock` / `yfinance` / `adata` / `hithink`，只能经 `sources/registry.py` |
| `respect_dependency_direction` | `domain` → `repositories` → `sources` → `research` 的下层不得反向 import 上层 |
| `capability_interfaces_present` | `AGENTS.md` 第 2 条列出的 7 个 Source 能力接口必须存在 |

> 依赖方向白名单写在 `audit/architecture.py`；要放宽某条规则必须改代码并说明理由，
> 不允许"就这一次"。

### 数据规则（SQL 不变量）

| 规则 | 级别 | 内容 |
| --- | --- | --- |
| `rows_on_non_trading_days` | ERROR | 行情/派生行的日期必须在 `core.trading_calendar` 里（日历未覆盖的区间跳过判定） |
| `orphan_mart_rows` | ERROR | `mart` 派生行必须能对应到 `core` 事实（否则是历史脏数据残留） |
| `estimates_without_version` | ERROR | 估算值必须 `is_estimated = TRUE` 且 `calculation_version` 非空 |
| `mixed_calculation_versions` | WARN | 同一张派生表不许混多个口径版本（公式变了要整段重放） |
| `zero_substituted_for_unknown` | ERROR | 不可能为 0 的字段（份额/净值/IOPV/成交额/两融余额）出现 `<= 0` |
| `missing_source_metadata` | ERROR | 事实行必须有 `source` 与 `fetched_at` |
| `holdings_without_report_date` | ERROR | 持仓必须有披露报告期；**schema 守卫**：检查 `NOT NULL` 约束还在不在 |
| `incomplete_market_turnover` | WARN | 沪深成交额应当成对出现，只落一边说明上游缺了一边 |
| `future_data_in_research_snapshot` | ERROR | 研究派生行不得领先于它依赖的事实（mart 日期晚于对应 core 事实 = 用到了当时不存在的数据） |

### 架构规则补充（V2 Phase 1）

| 规则 | 内容 |
| --- | --- |
| `research_sql_must_be_asof_bounded` | 研究查询（`repositories/research_repository.py`）凡按 `trade_date` 取最新行，必须同时带 as-of 约束；否则查历史会读到未来数据 |

### V2 Phase 2/3/5 新增规则

| 规则 | 级别 | 内容 |
| --- | --- | --- |
| `unadjusted_flow_crosses_corporate_action` | ERROR | 折算窗口内只有 v1 资金流口径、缺 v2 → 机械份额变化会被误读成申赎 |
| `adjusted_series_missing_version` | ERROR | 复权行缺口径版本，或版本未在 `domain/versions.py` 登记 |
| `adjusted_series_future_action_leak` | ERROR | 复权因子用了未来才知道的公司行为（Point-in-Time 泄漏） |
| `docs_consistency` | WARN | 结构化文档漂移：README/脚本里的 `etf <cmd>` 必须存在；代码里的 `calculation_version` 必须登记；迁移建的表必须写进 `DATA_MODEL.md` |

`mixed_calculation_versions` 的语义在 V2 更新为"出现**未登记**版本才告警"：
已登记版本允许并存（历史口径保留 + 新口径并行）。

### 上游契约检测（V2 Phase 5）

`ingestion/contracts.py` 把"上游 shape 变了"变成一条 `ops.quality_issue`：

| 检查 | 产出 |
| --- | --- |
| required columns | `<dataset>_schema_changed`（ERROR，附实际列名） |
| empty response | `<dataset>_empty_response`（默认 ERROR；来源允许空时 WARN） |
| response is None | `<dataset>_response_none`（ERROR） |
| timeout | `ingestion/retry.py: socket_timeout()` 兜底 |

已接线：净值（`etf_nav_daily`）、披露持仓（`etf_holding`）。其余适配器按同样方式补。

## 设计原则：每条规则都要能被触发

"干净库跑出 0 条"不能证明规则有效——它可能早就因为改表名、改字段而失效了。
因此 `tests/integration/test_audit_data_rules.py` 对**每条规则**都先造出违规数据、
确认被抓到，再验证干净数据不误报；`tests/unit/test_audit_architecture.py` 则在临时目录里
放一份"违规代码"，确认检查器真的会报。

实测这条原则立即见效：

* 三条规则（`estimates_without_version` 的 NULL 分支、`missing_source_metadata`、
  `holdings_without_report_date`）因为 schema 的 `NOT NULL` 约束**根本跑不到**。
  前两条改成检查"可触发形态"（`is_estimated=FALSE`、`source=''`），
  第三条改成 schema 守卫——顺手把"约束被去掉"这种静默漂移也纳入监控。
* DuckDB 对**主键列**执行 `ALTER COLUMN ... DROP NOT NULL` 不报错也不生效（实测），
  这个坑写进了测试注释，避免后人重复踩。

## 它已经抓到过什么

第一次在真实库上跑就抓到一条**有实际后果**的问题：

```text
✘ [ERROR] zero_substituted_for_unknown
    · core.etf_share_daily: shares 有 7 行 <= 0（缺失应记 NULL，不该填 0）
```

追查：`560650.SH` 的份额在 2026-08-21 起被上游写成 **0** 并持续 7 个交易日，
`compute_mart` 随即派生出一条 `share_change_1d = -7,919,200` 的"巨额赎回"，
进了 `mart.etf_flow_daily`。

修法是分层的（对应 `AGENTS.md` 的修 Bug 原则）：

1. **最小正确层**：`ingestion/validator.py` 的 `validate_share` 从"拒绝负数"
   收紧为"拒绝 `<= 0`"——0 份不可能是存续 ETF 的事实，只能是上游占位值；
   拦下 + 记 `ops.quality_issue`，不静默丢弃；
2. **清理既有脏数据**：删掉 7 条无效事实与 7 条由其派生的申赎行，
   并在 `ops.quality_issue` 留一条 `shares_positive_cleanup` 说明原委；
3. **补测试**：`tests/integration/test_share_nav_sync.py` 增加"份额 0 必须被拦下"的用例。

这条问题在被自检发现之前，只以"某只 ETF 有一笔莫名其妙的巨额赎回"的形式存在，
没有任何界面会提示它。

## 怎么扩展

加一条规则 = 三处改动：

1. 在 `DATA_RULES`（或架构规则表）里登记名称、级别、说明；
2. 实现检查函数并注册进 `_IMPLEMENTATIONS`；
3. **补一个"先违规、后干净"的测试**——没有这一步的规则不算完成。
