"""架构约束的静态检查（纯 AST，不联网、不碰数据库）。

对应 ``AGENTS.md``「不可破坏的架构约束」第 1 条与 ``docs/ARCHITECTURE.md`` 的依赖方向：

```text
CLI / API / MCP → Application Services → Research → Repositories → Sources
```

下层不许反向依赖上层；业务层不许直接调第三方金融库。
这些规则以前只写在文档里，靠自觉——现在由测试和 ``etf audit`` 强制执行。
"""

import ast
from dataclasses import dataclass
from pathlib import Path

#: 只允许出现在 ``sources/`` 里的第三方金融库。
FORBIDDEN_IN_BUSINESS_LAYERS = frozenset(
    {"akshare", "tushare", "efinance", "baostock", "yfinance", "adata", "hithink"}
)

#: 业务层目录（相对包根）。
BUSINESS_LAYERS = ("services", "research", "jobs", "api", "cli", "mcp")

#: 依赖方向：左边不许 import 右边。
FORBIDDEN_LAYER_IMPORTS: dict[str, frozenset[str]] = {
    "research": frozenset({"sources", "services", "jobs", "api", "cli", "mcp"}),
    "sources": frozenset({"research", "services", "jobs", "api", "cli", "mcp"}),
    "repositories": frozenset({"services", "jobs", "api", "cli", "mcp", "sources"}),
    "domain": frozenset(
        {"research", "sources", "repositories", "services", "jobs", "api", "cli", "mcp"}
    ),
}

#: ``AGENTS.md`` 第 2 条：这些能力接口必须一直存在。
REQUIRED_CAPABILITY_INTERFACES = (
    "ETFQuoteSource",
    "ETFHistorySource",
    "ETFShareSource",
    "ETFMasterSource",
    "ETFNavSource",
    "ETFHoldingSource",
    "IndexConstituentSource",
)


@dataclass(frozen=True, slots=True)
class ArchitectureRule:
    name: str
    description: str


ARCHITECTURE_RULES = (
    ArchitectureRule(
        "no_third_party_finance_in_business_layers",
        "业务层（services/research/jobs/api/cli/mcp）不得 import 第三方金融库，"
        "只能走 Source Adapter",
    ),
    ArchitectureRule(
        "respect_dependency_direction",
        "下层不得反向依赖上层（research/sources/repositories/domain 的 import 白名单）",
    ),
    ArchitectureRule(
        "capability_interfaces_present",
        "AGENTS.md 列出的 Source 能力接口必须存在（按能力拆，不按网站堆类）",
    ),
)


@dataclass(frozen=True, slots=True)
class ArchitectureViolation:
    rule: str
    path: str
    detail: str


def _iter_modules(package_root: Path):
    for path in sorted(package_root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        yield path


def _imported_modules(path: Path) -> set[str]:
    """模块里 import 的顶层模块名与 ``etf_engine.*`` 子模块名。"""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                modules.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                modules.add(node.module)
            # `from etf_engine.sources import x` 与 `from . import x` 都要覆盖
            if node.level and node.module is None:
                continue
    return modules


def _layer_of(relative: Path) -> str | None:
    return relative.parts[0] if len(relative.parts) > 1 else None


def check_architecture(package_root: Path) -> list[ArchitectureViolation]:
    """扫描包目录，返回全部架构违规（空列表 = 干净）。"""
    violations: list[ArchitectureViolation] = []
    interfaces_found: set[str] = set()

    # 能力接口定义在 sources/base.py，收集类名用于第三条规则。
    base_path = package_root / "sources" / "base.py"
    if base_path.exists():
        tree = ast.parse(base_path.read_text(encoding="utf-8"), filename=str(base_path))
        interfaces_found = {
            node.name
            for node in tree.body
            if isinstance(node, ast.ClassDef)
        }

    for path in _iter_modules(package_root):
        relative = path.relative_to(package_root)
        layer = _layer_of(relative)
        modules = _imported_modules(path)

        for module in modules:
            top = module.split(".")[0]
            if layer in BUSINESS_LAYERS and top in FORBIDDEN_IN_BUSINESS_LAYERS:
                violations.append(
                    ArchitectureViolation(
                        "no_third_party_finance_in_business_layers",
                        str(relative),
                        f"业务层直接 import 了 {module}；应通过 sources/registry.py 拿适配器",
                    )
                )

        forbidden = FORBIDDEN_LAYER_IMPORTS.get(layer or "")
        if not forbidden:
            continue
        for module in modules:
            parts = module.split(".")
            if parts[:1] == ["etf_engine"] and len(parts) > 1:
                target = parts[1]
            else:
                continue
            if target in forbidden:
                violations.append(
                    ArchitectureViolation(
                        "respect_dependency_direction",
                        str(relative),
                        f"{layer}/ 不能依赖 {target}/（import {module}）",
                    )
                )

    missing = [name for name in REQUIRED_CAPABILITY_INTERFACES if name not in interfaces_found]
    if missing:
        violations.append(
            ArchitectureViolation(
                "capability_interfaces_present",
                "sources/base.py",
                f"缺少能力接口：{', '.join(missing)}",
            )
        )

    return violations
