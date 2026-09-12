# Architecture

## 1. 系统边界

本项目负责：

```text
ETF Data
+
ETF Research
```

不负责：

```text
Portfolio Management
Broker Execution
News
Financial Statements
AI Report Writing
```

上层系统通过 CLI/API/MCP 调用本引擎。

## 2. 分层

```text
┌─────────────────────────────┐
│ CLI / REST / MCP            │
├─────────────────────────────┤
│ Application Services        │
├─────────────────────────────┤
│ Research Engine             │
├─────────────────────────────┤
│ Repositories                │
├─────────────────────────────┤
│ Core / Mart / Ops (DuckDB)  │
├─────────────────────────────┤
│ Ingestion Pipeline          │
├─────────────────────────────┤
│ Source Capability Adapters  │
├─────────────────────────────┤
│ SSE/SZSE/AKShare/HiThink    │
└─────────────────────────────┘
```

## 3. 依赖方向

上层可以依赖下层抽象。

下层不依赖：

- CLI
- API
- MCP
- AI

`research/` 不允许依赖 `sources/`。

## 4. 可替换性目标

未来将 AKShare 换成 Wind / Choice / 其他专业源时：

```text
Source Adapter 变化
```

而：

```text
Core Model
Research Engine
Service
API
```

尽量不变化。

这是 V1 最重要的架构目标之一。

## 5. Canonical Identifier

内部统一：

```text
588200.SH
159915.SZ
```

禁止用纯代码作为永久主键。

字段：

```text
security_id
ticker
exchange
asset_type
```

## 6. Fact / Derived / Opinion

Opinion 不进入 Core/Mart 的事实表。

如果后续保存 AI 解释，应单独建立：

```text
analysis.*
```

并保存：

- model
- prompt_version
- generated_at
- supporting_fact_snapshot

不能与金融事实混表。
