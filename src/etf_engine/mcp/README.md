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
```

正式接入 MCP SDK 时，仅在本目录添加 transport / tool registration。
