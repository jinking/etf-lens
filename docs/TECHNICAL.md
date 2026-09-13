# A股 ETF 研究引擎 V1 技术方案

## 1. 技术栈

- Python 3.12+
- Pandas / NumPy
- DuckDB
- Parquet
- FastAPI
- Typer
- Pytest
- AKShare
- SSE / SZSE 官方数据
- HiThink Financial API（第二数据源，按需启用）

## 2. 数据源原则

优先级：

```text
官方交易所
  ↓
稳定商业/官方服务
  ↓
AKShare 聚合
  ↓
其他备用源
```

但“优先级”不应写死在业务代码中，由能力 Registry / Policy 决定。

## 3. Source Adapter

按能力定义接口：

```text
ETFMasterSource
ETFQuoteSource
ETFHistorySource
ETFShareSource
ETFNavSource
ETFHoldingSource
IndexConstituentSource
TradingCalendarSource
```

看盘台（`docs/WATCHBOARD.md`）新增的市场层能力同样按能力拆，不按网站堆类：

```text
MarketTurnoverSource   # 交易所每日概况：SSE / SZSE 各一个适配器
MarginBalanceSource    # 两融余额（沪深分列）
MarketValuationSource  # 全 A 估值与历史分位
MarketActivitySource   # 涨跌家数 / 涨跌停 / 活跃度
FundIssuanceSource     # 新发基金（成立日期 + 募集份额，场外增量资金代理）
```

这些接口在 `sources/registry.py` 的 `SourceRegistry` 里注册为
`market_turnover_sources` / `margin_source` / `valuation_source` /
`market_activity_source`。

业务层不得直接依赖 AKShare 函数。

业务层（`jobs/`）只通过 `sources/registry.py` 的 `SourceRegistry` 获取适配器，
不直接 import 具体实现——否则"换数据源不改业务代码"这条目标立刻失效。

约定：适配器解析出的异常行由 `fetch_*_with_issues` 返回 `DataQualityIssue`，
由 job 写入 `ops.quality_issue`，不允许静默丢弃。

## 4. 数据流水线

```text
Fetch
  ↓
Raw Snapshot
  ↓
Normalize
  ↓
Validate
  ↓
Reconcile
  ↓
Upsert Core
  ↓
Compute Mart
```

所有同步必须幂等。

## 5. 数据质量

统一状态：

```text
VERIFIED
PASS
WARN
CONFLICT
STALE
FAILED
```

缺失使用 NULL。

异常数据不静默删除；保留到 `ops.quality_issue`。

## 6. 多源冲突

出现多个来源：

```text
source A = 1.253
source B = 1.279
```

超过容忍阈值：

```text
quality_status = CONFLICT
```

记录冲突值，不允许无声覆盖。

已落地的相关约束：`core.etf_quote_daily` 的 upsert 按列合并——历史回补来源
（新浪）不提供 `iopv` / 买卖盘 / 资金流，不能用 NULL 覆盖快照已写入的值。

### 6.1 未复权序列的处理

`core.etf_quote_daily.close` 与 `core.etf_nav_daily.unit_nav` 都是**未复权**事实。
份额折算/拆分/分红会让序列出现机械跳变（实测 515880.SH 在 2026-07-03 做了 2:1
份额折算，单位净值当日 -50%，而同期指数仅 -5%）。

因此研究层（`research/corporate_actions.py`）会检测窗口内的异常跳变
（默认阈值 20%，A 股 ETF 有涨跌停，真实行情不会超过），命中时：

- `simple_return` / `annualized_volatility` / `max_drawdown` / `current_drawdown` /
  `tracking_error` 一律返回 NULL，绝不给出跨除权的错误数值；
- 接口的 `quality.reasons` 给出真实原因
  （`corporate_action_in_window` / `nav_not_adjusted_for_corporate_actions`）。

复权净值（或前复权收盘价）应作为独立字段另行采集，而不是就地覆盖原始事实。

## 7. Research Engine

只处理标准化 Core Facts。

主要指标：

- return_1d / 5d / 20d / 60d
- volatility_20d / 60d
- max_drawdown_60d / 250d
- current_drawdown
- avg_turnover_5d / 20d / 60d
- share_change_1d / 5d / 20d / 60d
- estimated_net_subscription
- consecutive_share_inflow_days
- top5 / top10 concentration

每个派生指标带 `calculation_version`。

## 8. 时间

交易数据使用：

```text
Asia/Shanghai
```

同步必须基于交易日历，不使用 Monday-Friday 简化判断。

实现方式：

- `core.trading_calendar` 保存权威交易日（`etf sync-calendar`）；
- as-of 日期只由 `jobs/sync_shares.py` 一处解析：非交易日/未到发布时点回退到上一交易日；
- 历史区间按交易日推进（`MarketCalendar.trading_days_back`），不按自然日；
- 快照类来源（无自带日期）必须在库中记录 `share_snapshot_date_derived`。

## 9. 调度

V1 不把 Scheduler 绑进 FastAPI。

推荐：

- macOS：launchd
- Linux：systemd timer / cron

收盘后分阶段执行：

```text
quotes
history
shares
nav
metrics
pulse
```

已落地模板：

```text
scripts/run_daily.sh              # 每日：日历 → 行情 → 净值 → 份额 → 市场层 → mart → 看盘状态
scripts/run_weekly.sh             # 每周：净值回补 / ETF→指数映射 / 指数长历史 / 成交额回补
scripts/launchd/com.etf-lens.daily.plist   # macOS launchd 模板（改路径后 load）
```

约定：每日与每周链路都**尽力而为**（单步失败不阻断后续步骤，最后以非 0 退出码
上报），因为份额、折溢价、成交额这类数据一天不跑就永久缺一天。所有写库任务
必须**串行**——DuckDB 是单写进程，并发跑同类任务会互相抢文件锁。

未就绪数据允许 PENDING + 有界重试。

## 10. API

API 统一前缀：

```text
/api/v1
```

响应：

```json
{
  "data": {},
  "meta": {
    "asof_date": "2026-08-13",
    "quality": "PASS"
  },
  "errors": []
}
```

## 11. MCP

MCP 不直接开放 SQL。

建议工具：

- search_etfs
- get_etf_profile
- get_etf_quote
- get_etf_performance
- get_etf_flow
- get_etf_holdings
- compare_etfs
- screen_etfs

全部调用同一 Application Service 层。

现状：8 个工具已在 `src/etf_engine/mcp/tools.py` 实现并可单测，transport 在
`src/etf_engine/mcp/server.py`（FastMCP，可选依赖 `.[agent]`），`etf mcp` 启动。

## 11.1 Point-in-Time 研究上下文（V2 Phase 1）

研究查询（Compare / Screener / Themes）一律接受 as-of 上下文，只使用
``trade_date <= asof_date`` 的数据，并逐块返回真实 as-of 与滞后天数；
超期/缺失/口径不符的块置空并说明原因。

实现与契约见 [`docs/POINT_IN_TIME.md`](POINT_IN_TIME.md)，规则由 `etf audit` 的
`research_sql_must_be_asof_bounded` 与 `future_data_in_research_snapshot` 守护。

## 13. 单标的回补任务

有两类数据没有"全市场一次拉完"的接口，必须逐只标的请求，因此单独做成
有界、限速、可续跑、带退避重试的任务，不放进日常同步链路：

```text
etf backfill-nav      --days 60 --limit 50     # 逐只基金净值历史
etf sync-index-map    --limit 50               # 逐只 ETF 跟踪标的
etf sync-industry                              # 逐只个股行业分类（默认只取已持有个股）
etf sync-shares --backfill-days 40             # 逐交易日回补上交所份额
```

共同约定：单点失败只影响该标的（记入 `ops.quality_issue` 与 `ops.source_health`），
接口抖动由 `ingestion/retry.py` 做指数退避；失败不会写出半成品数据。

另外：AKShare 的多个包装函数内部是裸 `requests.get`，不带 `timeout`，上游卡住会让
任务无限期挂起（实测出现过 13 分钟不返回）。适配器统一用
`ingestion/retry.py: socket_timeout()` 兜底；能直接请求的接口（上交所份额、
深交所列表、中证指数行情、基金概况页）改成自带 `timeout` 的直接请求。

## 14. 指数行情来源

指数行情按来源能力依次尝试，`core.index_quote_daily.source` 记录每行实际来源：

```text
新浪指数日线（sh000300 这类行情符号）
  ↓ 没有符号或返回空
中证指数官网日线（中证自编主题指数，如 931160 中证全指通信设备）
```

两者都取不到时记 `index_quote_unavailable`，不留空值冒充数据。

## 12. 测试

- Unit
- Adapter Contract
- Fixture
- Integration
- Live Smoke（`pytest -m live`）
- 幂等测试
- 数据回归测试

Live Test 不进入普通 CI 默认路径。

当前覆盖：标识符（含 `.BJ` / `.HK`）、交易日历、份额/净值/持仓解析 fixture、
行情按列合并、看板口径、份额同步端到端（打桩上游，不访问网络）。
