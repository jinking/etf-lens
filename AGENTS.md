# AI Agent 开发入口

所有 Agent 第一次进入项目时，按以下顺序阅读：

1. `README.md`
2. `docs/PRODUCT.md`
3. `docs/ARCHITECTURE.md`
4. `docs/DATA_MODEL.md`
5. `docs/TECHNICAL.md`
6. `docs/ROADMAP.md`

## 不可破坏的架构约束

### 1. 不允许业务层直接调用第三方金融库

错误：

```python
import akshare as ak
df = ak.fund_etf_spot_em()
```

出现在 `services/`、`research/`、`api/`、`cli/` 中。

正确：

```text
Service
  ↓
Repository / Source Capability Interface
  ↓
Adapter
  ↓
AKShare / SSE / SZSE / HiThink
```

### 2. Source Adapter 按“能力”拆，不按网站堆成巨型类

必须保持这些能力接口：

- `ETFQuoteSource`
- `ETFHistorySource`
- `ETFShareSource`
- `ETFMasterSource`
- `ETFNavSource`
- `ETFHoldingSource`
- `IndexConstituentSource`

### 3. Raw / Core / Mart 分层不能省略

- `raw`：抓取快照，不做业务修饰；
- `core`：标准化事实；
- `mart`：确定性派生研究指标；
- `ops`：同步运行、数据质量、数据源健康度。

### 4. 缺失值使用 NULL，不用 0 代替

未知 ≠ 0。

### 5. ETF 交易资金和申赎资金必须分离

- `trading_flow_*`：二级市场大中小单等资金指标；
- `subscription_flow_*`：依据份额变化估算的申赎趋势。

禁止统称为 `money_flow`。

### 6. 估算值必须明确标记

所有估算资金必须：

```text
is_estimated = true
calculation_version = flow_v1
```

### 7. 持仓必须带披露日期

公开基金持仓不是实时组合。

### 8. 任何计算公式变化都要升级 calculation_version

不得静默修改历史口径。

## 修 Bug 原则

1. 先复现；
2. 找根因；
3. 修复最小正确层；
4. 补测试；
5. 检查是否属于通用类问题；
6. 避免只在业务层打补丁绕开 Adapter / Normalizer 问题。

## V1 开发优先级

P0：

```text
ETF Master
ETF Quote
ETF Historical
ETF Share
ETF Flow
```

P1：

```text
NAV
ETF → Index
Index Constituents
Holdings
Research Metrics
Compare
Screen
```

P2：

```text
REST API
MCP
Theme Aggregation
```
