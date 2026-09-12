#!/usr/bin/env bash
set -euo pipefail

# 收盘后的最小 V1 数据链路。
# 顺序有依赖：交易日历 → 行情/净值 → 份额（份额入库时用净值补 estimated_aum）→ mart。
# 仍未包含：重试/退避、数据就绪检测、调度器模板（见 docs/ROADMAP.md Phase 6）。

etf sync-calendar
etf sync-quotes
etf sync-nav
etf sync-shares
etf compute-mart
