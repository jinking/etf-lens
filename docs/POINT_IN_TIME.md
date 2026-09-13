# Point-in-Time 研究口径（V2 Phase 1）

## 1. 要解决的问题

升级前，Compare / Screener 对每张表各自取"最新一行"，于是可能出现：

```text
quote  = 2026-09-12
share  = 2026-09-11
metric = 2026-09-12
flow   = 2026-09-10
```

四个不同日期的数据被拼成一条"研究结论"，却不说明各自是哪天的；更严重的是，
**查历史某一天时会读到那天之后才产生的数据**（未来数据），任何历史回放、
walk-forward 验证都会因此失真。

## 2. 规则

```text
1. 查询一律 trade_date <= asof_date；
2. asof_date 为空 = "各自取最新可得"（兼容旧行为），但仍逐块返回真实 as-of；
3. 每块数据都带 *_asof_date 与 *_staleness_days；
4. 超过 max_staleness_days 的块视为不可用：字段置 NULL + 记录原因；
5. require_same_trade_date=true 时，只有与 as-of 同一天的块才可用；
6. 缺失/过期/未来/口径不符，一律 NULL——不插值、不就近取、不用 0 顶替。
```

实现分两层，避免两条查询路径口径分叉：

```text
repositories/research_repository.py   SQL：as-of 截断 + 返回各块 as-of 与口径版本
domain/research_context.py            策略：新鲜度、未来数据、版本一致性、裁剪
```

## 3. 输出契约

Compare 与 Screener 的每一行都包含：

```text
research_asof_date        本次研究的截止日（未指定时为 null）
quote_asof_date           行情块实际用到的日期
share_asof_date           份额块
metric_asof_date          指标块
flow_asof_date            资金流块
quote_staleness_days      该块滞后天数（未指定 as-of 时为 null）
share_staleness_days
metric_staleness_days
flow_staleness_days
stale_blocks              被置空的块与原因，如 ["flow:stale", "metric:missing"]
data_quality              PASS / PARTIAL
```

原因取值：

```text
missing               该块在该时点没有数据
future_data           块日期晚于 as-of（正常情况下 SQL 已拦住，防御性判定）
stale                 滞后超过 max_staleness_days
not_same_trade_date   要求同日，但该块不是当天
calculation_version_mismatch  口径版本与要求不一致
```

## 4. 用法

```bash
etf compare 510300.SH 159915.SZ --asof 2026-09-01
etf compare 510300.SH --asof 2026-09-11 --require-same-day
etf screen --tag 半导体 --min-aum 2000000000 --asof 2026-09-11 --max-staleness-days 3
```

```text
GET /api/v1/research/compare?security_ids=510300.SH&asof_date=2026-09-01
GET /api/v1/research/screen?min_aum=2000000000&asof_date=2026-09-11&max_staleness_days=3
GET /api/v1/research/themes?asof_date=2026-09-11
```

MCP 工具 `compare_etfs` / `screen_etfs` 同样接受 `asof_date`、`max_staleness_days`。

## 5. 筛选语义

数值条件（规模、成交额、收益、回撤、份额增长）在**新鲜度裁剪之后**判定：

```text
SQL 只负责 as-of 截断 + 关键词/标签过滤
        ↓
策略把过期/缺失的块置空
        ↓
数值条件在置空后的行上判定（NULL 永不满足条件）
```

因此一条"看起来满足门槛、其实用的是过期数据"的记录不可能通过筛选。

## 6. 自检

```text
research_sql_must_be_asof_bounded   研究查询（repositories/research_repository.py）
                                    凡按 trade_date 取最新行，必须带 as-of 约束
future_data_in_research_snapshot    派生行不得领先于其依赖的事实
```

第一条是静态检查（AST），第二条是数据不变量（SQL）。两条都有"先违规、后干净"的测试。

## 7. 已知边界

* 看板（Watchboard）与行情检索（`search_latest`、`dashboard_summary`）是"当前状态"
  查询，不在此约束范围内；纳入时需要把它们改成 as-of 感知并同步本文档。
* 公司行为（份额折算）会让跨折算区间的研究值不可用（见 `docs/TECHNICAL.md` §6.1），
  真正的修复是 V2 Phase 2 的复权序列。
