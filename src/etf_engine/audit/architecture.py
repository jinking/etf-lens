"""架构约束的静态检查（纯 AST，不联网、不碰数据库）。

对应 ``AGENTS.md``「不可破坏的架构约束」第 1 条与 ``docs/ARCHITECTURE.md`` 的依赖方向：

```text
CLI / API / MCP → Application Services → Research → Repositories → Sources
```

下层不许反向依赖上层；业务层不许直接调第三方金融库。
这些规则以前只写在文档里，靠自觉——现在由测试和 ``etf audit`` 强制执行。
"""

import ast
import re
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
    ArchitectureRule(
        "research_sql_must_be_asof_bounded",
        "研究查询不得无界取最新行：凡按 trade_date 取最新行的函数，"
        "必须同时带 as-of 约束（V2 Point-in-Time）",
    ),
    ArchitectureRule(
        "research_query_requires_explicit_version",
        "研究查询读取允许同日多版本的 mart 表（metric/flow）时，必须显式指定 "
        "calculation_version，不能让 ROW_NUMBER 的 tie-break 决定用哪一版（V2.1 P0-1）",
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
        interfaces_found = {node.name for node in tree.body if isinstance(node, ast.ClassDef)}

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

    violations.extend(_research_asof_violations(package_root))
    violations.extend(_research_version_violations(package_root))
    return violations


#: 判定"取最新一行"的 SQL 特征。
_LATEST_ROW_MARKERS = ("ROW_NUMBER() OVER", "ORDER BY trade_date DESC")

#: 只要出现其中之一，就认为该查询已经受 as-of 约束。
_ASOF_MARKERS = ("IS NULL OR", "<= ?")

#: 只对研究查询面强制 as-of。债券/看板这类"当前状态"查询是另一回事：
#: 它们展示的是"现在"，而不是"某个历史时点的研究结论"，要纳入时先改这里并同步文档。
_ASOF_SCOPED_MODULES = ("research_repository.py",)

#: 允许"同一天同时存在 v1/v2"的 mart 表：读它们时必须显式指定口径版本。
_VERSIONED_MART_TABLES = ("mart.etf_metric_daily", "mart.etf_flow_daily")

#: ``_latest_cte("latest_metrics", "mart.etf_metric_daily", ..., versioned=True)``
_LATEST_CTE_CALL = re.compile(
    r"_latest_cte\(\s*\"(?P<name>[^\"]+)\"\s*,\s*\"(?P<table>[^\"]+)\"(?P<args>[^)]*)\)"
)


def _function_string_literals(node: ast.AST) -> list[str]:
    return [
        child.value
        for child in ast.walk(node)
        if isinstance(child, ast.Constant) and isinstance(child.value, str)
    ]


def _research_version_violations(package_root: Path) -> list[ArchitectureViolation]:
    """研究查询读"同日多版本"的表时，必须显式指定 ``calculation_version``。

    ``mart.etf_metric_daily`` / ``mart.etf_flow_daily`` 允许
    ``security_id + trade_date + calculation_version`` 并存 v1/v2。若查询只按
    ``trade_date DESC`` 取最新一行，同一天取到哪一版由执行计划决定——
    同一问题重复执行可能得到不同结论（V2.1 P0-1 就是这个问题）。

    检查点很具体：``_latest_cte(..., "mart.etf_metric_daily", ...)`` 这类调用
    必须带 ``versioned=True``，否则记违规。
    """
    violations: list[ArchitectureViolation] = []
    for path in sorted((package_root / "repositories").rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        source = path.read_text(encoding="utf-8")
        for match in _LATEST_CTE_CALL.finditer(source):
            if match.group("table") not in _VERSIONED_MART_TABLES:
                continue
            if "versioned=True" in match.group("args"):
                continue
            violations.append(
                ArchitectureViolation(
                    "research_query_requires_explicit_version",
                    f"{path.relative_to(package_root)}::{match.group('name')}",
                    f"读取 {match.group('table')} 时没有显式指定 calculation_version",
                )
            )
    return violations


def _research_asof_violations(package_root: Path) -> list[ArchitectureViolation]:
    """研究查询必须能限定 as-of（找"取最新行但无时间边界"的函数）。

    触发条件：一个函数里出现"取最新行"的 SQL 特征，却没有任何 as-of 约束标记。
    这类查询在查历史日期时会读到当天之后的数据，V2 之后不允许。
    """
    violations: list[ArchitectureViolation] = []
    repositories = package_root / "repositories"
    if not repositories.exists():
        return violations

    for path in sorted(repositories.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        if path.name not in _ASOF_SCOPED_MODULES:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef):
                continue
            literals = _function_string_literals(node)
            if not literals:
                continue
            blob = "\n".join(literals)
            if not all(marker in blob for marker in _LATEST_ROW_MARKERS):
                continue
            if any(marker in blob for marker in _ASOF_MARKERS):
                continue
            violations.append(
                ArchitectureViolation(
                    "research_sql_must_be_asof_bounded",
                    f"{path.relative_to(package_root)}::{node.name}",
                    "SQL 按 trade_date 取最新行但没有 as-of 约束（<= asof_date）",
                )
            )
    return violations
