"""V2.1 总体验收（升级方案 §20–21）：把 Case A–E 变成可重复执行、有证据的检查。

它不做任何新的研究计算，只做两件事：

1. 逐个跑"每个 Case 对应的最小验证测试"，把通过/失败与耗时记下来；
2. 把结果连同环境信息（commit、as-of、时间）写成 ``docs/V2_1_ACCEPTANCE.md``。

Case E（GitHub Actions 全绿）依赖外部系统：装了 ``gh`` 且已登录时直接查最近一次
run；查不到就如实写 ``UNKNOWN``，不拿"本地绿"冒充。

用法::

    python scripts/v2_1_acceptance.py --write-doc
"""

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

DEFAULT_DOC = Path("docs/V2_1_ACCEPTANCE.md")
ASOF = "2026-09-11"

SPLIT_CASE = "tests/integration/test_corporate_action_pipeline.py"
VERSION_CASE = "tests/integration/test_version_routing.py"

#: Case → 对应的最小验证测试（升级方案 §21）。
CASES: list[tuple[str, str, list[str]]] = [
    (
        "A",
        "515880 拆分：metric_v2 收益/回撤、flow_v2、tracking 不再出现假 -50% / 假巨额申赎",
        [
            f"{SPLIT_CASE}::test_split_no_longer_creates_fake_returns_or_subscriptions",
            f"{SPLIT_CASE}::test_adjusted_series_is_point_in_time_safe",
            f"{SPLIT_CASE}::test_audit_flags_unadjusted_flow_across_a_split",
        ],
    ),
    (
        "B",
        "现金分红：adjusted_shares 不变，flow_v2 不制造假赎回，净值收益保持连续",
        [
            f"{SPLIT_CASE}::test_cash_dividend_does_not_create_a_fake_redemption",
            f"{SPLIT_CASE}::test_cash_dividend_keeps_nav_returns_continuous",
        ],
    ),
    (
        "C",
        "同日 v1/v2 并存：普通 Compare 稳定返回 v2（重复 100 次结果一致）",
        [
            f"{VERSION_CASE}::test_compare_uses_the_production_version",
            f"{VERSION_CASE}::test_screen_uses_the_production_version",
            f"{VERSION_CASE}::test_repeated_compare_is_byte_for_byte_stable",
        ],
    ),
    (
        "D",
        "历史 Point-in-Time：Tag / Holdings / Peer / Tracking / Profile 不回看未来",
        [
            "tests/integration/test_pit_tags.py",
            "tests/integration/test_pit_holdings.py",
            "tests/integration/test_pit_peer.py",
            "tests/integration/test_pit_profile.py",
        ],
    ),
]


def _run(command: list[str]) -> tuple[int, str]:
    completed = subprocess.run(command, capture_output=True, text=True, check=False)
    return completed.returncode, (completed.stdout + completed.stderr).strip()


def _git_sha() -> str:
    code, out = _run(["git", "rev-parse", "--short", "HEAD"])
    return out if code == 0 else "UNKNOWN"


def _ci_status() -> tuple[str, str]:
    """最近一次普通 CI 的状态。没有 gh / 没登录 / 没网络时如实报 UNKNOWN。"""
    code, out = _run(
        [
            "gh",
            "run",
            "list",
            "--workflow",
            "ci.yml",
            "--limit",
            "1",
            "--json",
            "conclusion,status,url,headSha,createdAt",
        ]
    )
    if code != 0 or not out:
        return "UNKNOWN", "本地未安装 gh / 未登录 / 无网络，请到 GitHub Actions 页面确认"
    try:
        runs = json.loads(out)
    except json.JSONDecodeError:
        return "UNKNOWN", out[:200]
    if not runs:
        return "UNKNOWN", "还没有 CI run 记录"
    run = runs[0]
    status = run.get("conclusion") or run.get("status") or "UNKNOWN"
    head = str(run.get("headSha", ""))[:7]
    return str(status), f"{run.get('url', '')}（head {head}）"


def run_cases() -> list[dict]:
    results: list[dict] = []
    for name, description, targets in CASES:
        started = datetime.now()
        code, out = _run([sys.executable, "-m", "pytest", "-q", "--no-header", *targets])
        elapsed = (datetime.now() - started).total_seconds()
        last_line = out.splitlines()[-1] if out else ""
        results.append(
            {
                "name": name,
                "description": description,
                "targets": targets,
                "passed": code == 0,
                "summary": last_line,
                "seconds": round(elapsed, 1),
            }
        )
    return results


def render(results: list[dict], *, ci_status: str, ci_detail: str, sha: str) -> str:
    overall = "PASS" if all(item["passed"] for item in results) else "FAIL"
    lines = [
        "# V2.1 总体验收（Case A–E）",
        "",
        "> 由 `python scripts/v2_1_acceptance.py --write-doc` 生成，可重复执行。",
        ">",
        f"> commit `{sha}` ｜ as-of `{ASOF}` ｜ 生成时间 {datetime.now():%Y-%m-%d %H:%M}",
        ">",
        f"> 总状态：**{overall}**",
        "",
        "## 1. Case A–D（每项都对应一段可执行的最小验证）",
        "",
        "| Case | 结论 | 内容 | 验证 | 耗时 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for item in results:
        mark = "✅ PASS" if item["passed"] else "❌ FAIL"
        targets = ", ".join(f"`{target}`" for target in item["targets"])
        lines.append(
            f"| {item['name']} | {mark} | {item['description']} | {targets} | {item['seconds']}s |"
        )

    lines += ["", "各 Case 的 pytest 末行输出：", ""]
    for item in results:
        lines.append(f"- **Case {item['name']}**：`{item['summary']}`")

    lines += [
        "",
        "## 2. Case E — GitHub Actions",
        "",
        f"- 普通 CI（`.github/workflows/ci.yml`）：**{ci_status}**",
        f"- 依据：{ci_detail}",
        "",
        "live 上游用例只在 `.github/workflows/live-smoke.yml` 跑，不阻塞 PR；",
        '普通 CI 用 `pytest -q -m "not live"`，保证干净环境可复现。',
        "",
        "## 3. 总体验收（研究链路，非测试）",
        "",
        "```text",
        f"python scripts/v2_acceptance.py --asof {ASOF} --write-doc",
        "```",
        "",
        "产物：`docs/V2_ACCEPTANCE.md`（国产算力 ETF · Point-in-Time 全链路）。",
        "历史 regime 验证报告：`etf validate-pulse --write-doc` → `docs/REGIME_VALIDATION.md`。",
        "",
        "## 4. 结论边界",
        "",
        "- Case A–D 是**确定性回归**：同样的库、同样的 as-of，重复执行必须同样通过；",
        "- Case E 依赖外部 CI 服务，本地只能查到「最近一次」，不替代 CI 本身的结论；",
        "- 本文件覆盖「正确性」，不覆盖「行情观点」——系统不产出买卖建议。",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="V2.1 总体验收（Case A–E）")
    parser.add_argument("--write-doc", action="store_true")
    parser.add_argument("--doc", default=str(DEFAULT_DOC))
    parser.add_argument("--skip-ci", action="store_true", help="不查询 gh（离线环境）")
    args = parser.parse_args()

    results = run_cases()
    if args.skip_ci:
        ci_status, ci_detail = "UNKNOWN", "本次运行显式跳过（--skip-ci）"
    else:
        ci_status, ci_detail = _ci_status()
    markdown = render(results, ci_status=ci_status, ci_detail=ci_detail, sha=_git_sha())

    if args.write_doc:
        target = Path(args.doc)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(markdown, encoding="utf-8")
        print(f"报告已写入 {target}")
    else:
        print(markdown)

    if not all(item["passed"] for item in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
