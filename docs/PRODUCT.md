# A股 ETF 研究引擎 V1 产品方案

## 1. 产品定位

本项目定位为：

> 面向个人投资研究、AI Agent 和投资报告系统的 A 股 ETF 数据与研究基础设施。

不是“查一个价格”的工具，而是持续积累 ETF 数据、形成可比较研究指标的本地数据底座。

## 2. V1 需要回答的问题

1. 这是什么 ETF？
2. 当前表现如何？
3. 历史表现如何？
4. ETF 份额是增加还是减少？
5. 它跟踪什么指数？
6. 它暴露在哪些股票与行业？
7. 和同类 ETF 相比有什么差异？
8. 一个主题下有哪些 ETF？
9. 哪些 ETF 最近出现持续份额增加？

## 3. V1 核心功能

### P0

- ETF 主数据
- 收盘/实时行情快照
- ETF 历史日 K
- ETF 每日份额
- 份额变化
- 估算申赎资金

### P1

- ETF 净值
- ETF → 跟踪指数映射
- 指数当前成分与权重
- 基金披露持仓
- 收益 / 波动率 / 回撤 / 流动性
- ETF Compare
- ETF Screener

### P2

- 主题聚合
- CLI
- REST API
- MCP

## 4. 资金流口径

### 二级市场交易资金

来源于成交和大中小单等指标：

```text
trading_flow_main
trading_flow_super_large
trading_flow_large
trading_flow_medium
trading_flow_small
```

不能解释为 ETF 净申购。

### ETF 份额资金趋势

```text
share_change = shares_t - shares_t-1
estimated_subscription = share_change × NAV_t
```

这是估算值，不是基金公司现金流水。

## 5. ETF 详情页数据结构

### 基础档案

- 代码
- 名称
- 基金公司
- 上市日期
- 成立日期
- 费率
- 跟踪指数
- 最新规模/份额

### 行情

- 收盘价
- 涨跌幅
- 成交额
- 换手率
- IOPV
- 折溢价

### 历史表现

- 1D / 5D / 20D / 60D / YTD / 1Y
- 波动率
- 最大回撤
- 当前回撤

### 资金

- 1/5/20/60 日份额变化
- 连续份额增加天数
- 估算申购资金

### 暴露

- 跟踪指数
- Top10
- Top10 集中度
- 行业/主题标签

## 6. Compare

必须统一 `asof_date`，比较：

- 规模
- 流动性
- 费率
- 收益
- 波动率
- 回撤
- 份额变化
- 集中度

输出客观事实，不自动给买卖建议。

## 7. Screener

数据库筛选，而不是大模型遍历全部 ETF。

示例：

```text
theme = 国产算力
aum > 20亿
avg_turnover_20d > 1亿
share_change_20d > 0
max_drawdown_60d > -25%
```

## 8. V1 不做

- 自动交易
- AI 荐股
- 价格预测
- Level-2
- 新闻聚合
- 财报分析
- 复杂回测
- 券商连接

## 9. V1 成功标准

系统能够稳定、带来源地回答：

```text
etf show 588200.SH
etf compare A B C
etf screen --tag 国产算力
```

并且所有关键事实可追溯到原始数据。
