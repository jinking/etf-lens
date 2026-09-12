#!/usr/bin/env bash
set -euo pipefail

# 收盘后的最小 V1 数据链路。
# 正式生产前应增加交易日判断、重试、运行记录与数据就绪检测。

etf sync-quotes
etf sync-shares
