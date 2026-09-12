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
```

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
etf sync-quotes
etf sync-shares
etf show 588200.SH
```

> `sync-*` 命令需要网络和对应上游接口可用。

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
