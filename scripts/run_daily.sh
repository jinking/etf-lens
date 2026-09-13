#!/usr/bin/env bash
set -uo pipefail

# 收盘后的日常数据链路（含看盘台市场层）。
#
# 顺序有依赖：
#   交易日历 → 行情/净值 → 份额（份额入库时用净值补 estimated_aum）
#   → 市场层（成交额/两融/估值/涨跌家数）→ mart → 三层状态
#
# 行为约定：
#   * **尽力而为**：某一步失败不阻断后续步骤——份额/折溢价这类数据一天不跑就
#     永久缺一天，不能因为上游抖动整条链路停摆；
#   * 失败会逐条打印，并在结束时以非 0 退出码上报，便于 launchd/cron 告警；
#   * 全程串行：DuckDB 是单写进程，同类任务不能并发跑。
#
# 用法：
#   scripts/run_daily.sh              # 正常每日跑
#   scripts/run_daily.sh --skip-heavy # 跳过档案补齐等较慢步骤

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

if [ -f ".venv/bin/activate" ]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

SKIP_HEAVY=0
if [ "${1:-}" = "--skip-heavy" ]; then
  SKIP_HEAVY=1
fi

FAILED=()

run_step() {
  local label="$1"
  shift
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] ▶ ${label}"
  if "$@"; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ✔ ${label}"
  else
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ✘ ${label}（继续执行后续步骤）" >&2
    FAILED+=("${label}")
  fi
}

run_step "交易日历" etf sync-calendar
run_step "行情快照" etf sync-quotes
run_step "净值" etf sync-nav
run_step "份额" etf sync-shares
# 市场层：当天成交额/两融/估值/涨跌家数/指数估值，逐日积累（深市份额同理只能逐日积累）
run_step "市场层" etf sync-market --backfill-days 1

if [ "$SKIP_HEAVY" -eq 0 ]; then
  run_step "基金档案" etf sync-fund-profile --limit 20
  run_step "公司行为" etf sync-corporate-actions --limit 20
  run_step "复权序列" etf compute-adjusted-series
fi

run_step "研究指标" etf compute-mart
run_step "同类分位" etf peer-metrics
run_step "市场标准化" etf market-norm
run_step "看盘三层状态" etf pulse
# 自检放在最后：架构约束 + 数据不变量，有 ERROR 就以非 0 退出码上报
run_step "自检" etf audit

if [ "${#FAILED[@]}" -gt 0 ]; then
  echo
  echo "以下步骤失败，请检查 ops.quality_issue 与 ops.source_health：" >&2
  for step in "${FAILED[@]}"; do
    echo "  - ${step}" >&2
  done
  exit 1
fi

echo
echo "每日链路完成。看盘台：etf api 后打开 http://127.0.0.1:8000/watchboard"
