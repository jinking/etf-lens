#!/usr/bin/env bash
set -uo pipefail

# 每周回补链路：补那些"没有全市场一次拉完"接口的数据。
#
# 这些任务逐标的/逐交易日请求，跑一次要几分钟到几十分钟，因此不进每日链路：
#   * 净值历史：解锁 5/20 日申赎估算（净值不足时估算返回 NULL，不降级近似）；
#   * ETF→指数映射：宽基篮子覆盖度直接取决于它；
#   * 指数长历史：位置分位与 3 年窗口；
#   * 成交额回补：把逐日缺口补齐，维持 250 日分位窗口。
#
# 用法：scripts/run_weekly.sh [--limit 300]

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_ROOT"

if [ -f ".venv/bin/activate" ]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

LIMIT=300
if [ "${1:-}" = "--limit" ] && [ -n "${2:-}" ]; then
  LIMIT="$2"
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

run_step "净值回补" etf backfill-nav --days 60 --limit "${LIMIT}"
run_step "申赎历史回填" etf backfill-flow
run_step "ETF→指数映射" etf sync-index-map --limit "${LIMIT}" --sleep 0.1
run_step "指数长历史" etf backfill-index-history --years 6
run_step "成交额回补" etf sync-market --backfill-days 250
run_step "状态历史回放" etf backfill-pulse --days 250
run_step "研究指标" etf compute-mart
run_step "看盘三层状态" etf pulse

if [ "${#FAILED[@]}" -gt 0 ]; then
  echo
  echo "以下步骤失败，请检查 ops.quality_issue 与 ops.source_health：" >&2
  for step in "${FAILED[@]}"; do
    echo "  - ${step}" >&2
  done
  exit 1
fi

echo
echo "每周回补完成。"
