"""MCP transport：把 :mod:`etf_engine.mcp.tools` 注册成 MCP 工具。

MCP SDK 是可选依赖（``pip install -e ".[agent]"``）。没有安装时这里给出
明确提示，而不是在 import 阶段炸掉整个包。
"""

from collections.abc import Callable
from typing import Any

from etf_engine.mcp.tools import TOOL_FUNCTIONS


class MCPSdkNotInstalled(RuntimeError):
    """MCP SDK 未安装。"""


def _require_fastmcp():
    """拿到 MCP server 类；SDK 缺失或版本不兼容时给出可执行的提示。

    实测两个坑：

    * mcp 1.x 提供 ``mcp.server.fastmcp.FastMCP``；
    * mcp 2.x 移除了这个模块，且 import 它抛的**不是** ImportError（是一个
      提示"已改名为 MCPServer"的自定义异常），只捕 ImportError 会漏掉——
      CI 就是这样红的。
    """
    try:
        from mcp.server.fastmcp import FastMCP

        return FastMCP
    except Exception:
        pass
    try:
        # mcp 2.x 的新位置。工具注册 API 是否完全兼容尚未验证，
        # 因此这里只保证"能构造 server"（兼容性验证记在 ROADMAP）。
        from mcp.server.mcpserver import MCPServer

        return MCPServer
    except Exception as exc:
        raise MCPSdkNotInstalled(
            '未安装可用的 MCP SDK：请执行 `pip install -e ".[agent]"`，'
            "或安装 mcp 1.x（`pip install 'mcp<2'`）。"
        ) from exc


def build_server(name: str = "etf-lens") -> Any:
    """构造 MCP server，并把全部工具注册进去。"""
    fast_mcp = _require_fastmcp()
    server = fast_mcp(name)
    for tool_name, function in TOOL_FUNCTIONS.items():
        server.tool(name=tool_name)(function)
    return server


def run_stdio() -> None:
    """以 stdio transport 启动；供 ``etf mcp`` 调用。"""
    build_server().run()


def tool_registry() -> dict[str, Callable[..., Any]]:
    """不依赖 SDK 的工具清单，便于自检与测试。"""
    return {name: function for name, function in TOOL_FUNCTIONS.items()}
