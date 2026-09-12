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
```

业务层不得直接依赖 AKShare 函数。

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
```

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

## 12. 测试

- Unit
- Adapter Contract
- Fixture
- Integration
- Live Smoke（`pytest -m live`）
- 幂等测试
- 数据回归测试

Live Test 不进入普通 CI 默认路径。
