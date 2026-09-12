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
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:  # pragma: no cover - 取决于运行环境
        raise MCPSdkNotInstalled(
            '未安装 MCP SDK，请执行 `pip install -e ".[agent]"` 后重试。'
        ) from exc
    return FastMCP


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
