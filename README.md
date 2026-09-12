# ETF Research Engine

A股 ETF 本地数据底座与研究查询引擎。

## V1 目标

本项目不是交易系统，也不是荐股系统。V1 只解决四件事：

1. 采集 A 股 ETF 基础资料、行情、历史 K 线、份额、净值、披露持仓、跟踪指数与指数成分；
2. 把外部接口数据标准化并长期保存到本地；
3. 计算收益、波动率、回撤、流动性、份额变化、估算申赎资金、集中度等确定性研究指标；
4. 通过 CLI / REST API / MCP-ready Service 层向上层日报、Agent、组合系统提供统一查询能力。

## 核心原则

```text
External Sources
      ↓
Source Adapter
      ↓
Raw Snapshot
      ↓
Normalizer
      ↓
Validator / Reconciler
      ↓
Core Facts (DuckDB)
      ↓
Research Engine
      ↓
Research Mart
      ↓
CLI / REST / MCP
```

严格区分：

- Fact：交易所 / 数据源提供的事实数据；
- Derived：系统确定性计算得到的数据；
- Opinion：上层 AI 的解释与判断。

AI 不修改底层事实数据。

## 快速开始

推荐 Python 3.12+。

### 一键初始化

```bash
chmod +x scripts/init_local.sh
./scripts/init_local.sh
```

### 手动初始化

```bash
cp .env.example .env
python -m venv .venv
source .venv/bin/activate

pip install -e ".[dev]"

python scripts/bootstrap.py
etf doctor
etf db-init
etf sync-calendar
```

> `etf sync-calendar` 必须先执行：份额/净值等收盘后数据依赖交易日历判断 as-of
> 日期，缺失时同步任务会直接报错并给出提示。

启动 API：

```bash
etf api
```

默认：

```text
http://127.0.0.1:8000
```

启动后直接在浏览器打开：

```text
http://127.0.0.1:8000/
```

网页研究台会显示本地数据状态、市场概览、ETF 搜索与最新行情详情。首次使用时，点击“同步最新行情”即可从 AKShare 拉取全市场 ETF 行情并写入本地 DuckDB。

也可以通过接口同步：

```bash
curl -X POST http://127.0.0.1:8000/api/v1/sync/quotes
```

检查：

```bash
curl http://127.0.0.1:8000/health
```

## 第一批命令

```bash
etf doctor
etf db-init
etf sync-calendar        # 同步交易日历（其余任务的前置）
etf sync-master          # ETF 主数据
etf sync-quotes
etf sync-nav             # ETF 单位净值
etf sync-shares
etf sync-shares --backfill-days 40   # 仅上交所支持按交易日回补
etf backfill-nav --days 60 --limit 50 # 逐只基金回补净值历史（解锁 5/20 日申赎估算）
etf sync-holdings        # 披露持仓 + 行业穿透标签
etf sync-industry        # 个股行业分类（cninfo，A 股口径）
etf sync-fund-profile    # 补齐费率/成立日期/管理人等档案字段（沪深都能拿到）
etf sync-index-catalog   # 指数目录
etf sync-index-map --limit 50        # ETF→跟踪指数（按基金披露的跟踪标的）
etf sync-index-details   # 指数成分 + 指数行情
etf compute-mart         # 计算收益/波动/回撤/流动性/份额变化
etf show 588200.SH
etf metrics 588200.SH
etf screen --tag 半导体 --min-aum 2000000000
etf themes               # 主题聚合（行业/风格）
etf mcp                  # 以 stdio 启动 MCP server（需 .[agent]）
```

> `sync-*` 命令需要网络和对应上游接口可用。
> 逐只标的的任务（`backfill-nav` / `sync-index-map` / `sync-industry` / `sync-holdings`）
> 都支持 `--limit`/`--top-n` 分次推进，单点失败只影响该标的并记入 `ops.quality_issue`。

## 数据口径约束

- 交易日一律来自 `core.trading_calendar`，不用 Monday-Friday 近似；
- 交易资金（`trading_flow_*`）与申赎估算（`estimated_net_subscription_*`）分开；
- 估算值带 `is_estimated` 与 `calculation_version`；
- 跨源拼接（如"深交所份额 + 东方财富净值"）单独记录 `nav_source`；
- 解析/校验失败的行写入 `ops.quality_issue`，不静默丢弃。
- 行业分类来自 `core.stock_industry`（带分类标准），不在代码里维护映射字典；
  标签带 `coverage`，覆盖率不足时不输出"宽基/均衡"风格判断；
- ETF→指数映射来自基金披露的跟踪标的，与指数目录精确对齐，对不上不写映射。

## 数据目录

```text
data/
├── raw/          # 上游原始快照（Parquet）
├── warehouse/    # DuckDB
├── exports/      # CSV/Parquet 导出
└── backups/      # 本地备份
```

## 文档

- `docs/PRODUCT.md`：产品方案
- `docs/TECHNICAL.md`：技术方案
- `docs/ARCHITECTURE.md`：架构与边界
- `docs/DATA_MODEL.md`：数据模型
- `docs/ROADMAP.md`：V1 开发阶段
- `AGENTS.md`：给 Codex / Claude Code / Cursor 等 Agent 的开发入口

## V1 明确不做

- 自动交易
- 券商账户连接
- Level-2
- 高频策略
- 自动荐股
- AI 价格预测
- 新闻聚合
- 财报分析
- 重型回测平台

先把数据可信度、历史积累和研究指标做好。
