# MCP

V1 骨架先固定 MCP 边界，不绑定某一个快速变化的 SDK API。

原则：

```text
MCP Tool
  ↓
Application Service
  ↓
Repository / Research Engine
```

禁止 MCP Tool 直接：

- 调 AKShare；
- 执行任意 SQL；
- 写 Core Facts；
- 修改原始数据。

计划工具：

```text
search_etfs
get_etf_profile
get_etf_quote
get_etf_performance
get_etf_flow
get_etf_holdings
compare_etfs
screen_etfs
get_market_pulse
```

## 现状

工具已全部实现：

- `tools.py`：8 个工具函数，只做"参数 → Application Service → 可序列化结果"的编排，
  不依赖 MCP SDK，可直接单测；
- `server.py`：MCP transport（FastMCP），把工具注册进 server；SDK 是可选依赖
  （`pip install -e ".[agent]"`），未安装时抛出 `MCPSdkNotInstalled` 并给出安装提示，
  不会在 import 阶段炸掉整个包。

启动：

```bash
etf mcp          # stdio transport
```

`etf mcp` 需要先完成本地数据同步，否则工具会因为本地没有数据而报 404/LookupError——
这是刻意的：工具不访问上游，也不编造数据。
