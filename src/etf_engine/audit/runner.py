"""自检编排：跑架构规则 + 数据规则，汇总成一份可读报告。

退出码约定：有 ``ERROR`` 级违规 → 非 0；只有 ``WARN`` → 0（``--strict`` 时也非 0）。
这样它能直接挂在每日链路后面当守门人，也能被 Agent 当结构化输入消费。
"""

from pathlib import Path

from etf_engine.audit.architecture import check_architecture
from etf_engine.audit.data_rules import DATA_RULES, run_data_rules

SEVERITY_ERROR = "ERROR"
SEVERITY_WARN = "WARN"

#: 默认扫描的包目录（相对项目根）。
DEFAULT_PACKAGE_ROOT = Path("src/etf_engine")


def run_audit(
    *,
    package_root: Path | None = None,
    database_path: Path | None = None,
) -> dict:
    root = package_root or DEFAULT_PACKAGE_ROOT
    checks: list[dict] = []

    architecture_violations = check_architecture(root)
    checks.append(
        {
            "name": "architecture",
            "severity": SEVERITY_ERROR,
            "description": "AGENTS.md 的架构约束：依赖方向、业务层不碰第三方金融库、能力接口齐备",
            "violations": [
                {"dataset": item.path, "detail": f"[{item.rule}] {item.detail}"}
                for item in architecture_violations
            ],
            "count": len(architecture_violations),
        }
    )

    checks.extend(run_data_rules(database_path))

    errors = sum(
        check["count"] for check in checks if check["severity"] == SEVERITY_ERROR
    )
    warnings = sum(check["count"] for check in checks if check["severity"] == SEVERITY_WARN)
    return {
        "status": "PASS" if errors == 0 else "FAIL",
        "error_count": errors,
        "warning_count": warnings,
        "checks": checks,
        "rule_count": len(checks) + len(DATA_RULES) - len(DATA_RULES),
        "package_root": str(root),
        "database_path": str(database_path or ""),
    }


def format_report(result: dict, *, show_samples: int = 3) -> str:
    """把审计结果渲染成终端可读文本。"""
    lines = [
        f"ETF Lens 自检 · {result['status']}",
        f"ERROR {result['error_count']} · WARN {result['warning_count']}",
        "-" * 66,
    ]
    for check in result["checks"]:
        mark = "✔" if check["count"] == 0 else ("✘" if check["severity"] == SEVERITY_ERROR else "!")
        lines.append(f"{mark} [{check['severity']}] {check['name']}（{check['count']} 条）")
        lines.append(f"    {check['description']}")
        for violation in check["violations"][:show_samples]:
            lines.append(f"    · {violation['dataset']}: {violation['detail']}")
        if check["count"] > show_samples:
            lines.append(f"    · …另有 {check['count'] - show_samples} 条")
    return "\n".join(lines)
