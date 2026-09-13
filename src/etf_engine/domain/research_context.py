"""研究的 as-of 上下文（Point-in-Time）。

问题：Compare / Screener 之前对每张表各自取"最新一行"，于是可能出现

```text
quote  = 2026-09-12
share  = 2026-09-11
metric = 2026-09-12
flow   = 2026-09-10
```

被拼成同一条"研究结论"，却不说明各自是哪天的数据——查历史某一天时还会读到
当天之后才有的信息（未来数据）。

这里的规则：

1. 查询一律 ``trade_date <= asof_date``；``asof_date`` 为空时表示"各自取最新可得"，
   此时仍必须逐块返回真实 as-of；
2. 每块数据都带出自己的 ``*_asof_date`` 与 ``*_staleness_days``；
3. ``max_staleness_days`` 之外的块视为不可用（字段置 NULL 并记录原因），
   不插值、不就近取；
4. ``require_same_trade_date=True`` 时，只有与 as-of 同一天的块才可用；
5. 缺失块的字段一律 NULL，不做任何兜底填充。
"""

from dataclasses import dataclass, field
from datetime import date

#: 研究结果的数据块。每块都有自己的 as-of 与新鲜度。
RESEARCH_BLOCKS: tuple[str, ...] = ("quote", "share", "metric", "flow")

#: 各块在输出里的默认字段名（查询层可覆盖，例如 Screener 用 ``aum``）。
BLOCK_OUTPUT_COLUMNS: dict[str, tuple[str, ...]] = {
    "quote": ("close", "change_pct", "turnover_amount"),
    "share": ("shares", "estimated_aum"),
    "metric": ("avg_turnover_amount_20d", "return_20d", "return_60d", "max_drawdown_60d"),
    "flow": ("share_change_20d", "share_change_pct_20d", "estimated_net_subscription_20d"),
}

QUALITY_PASS = "PASS"
QUALITY_PARTIAL = "PARTIAL"

REASON_MISSING = "missing"
REASON_FUTURE = "future_data"
REASON_STALE = "stale"
REASON_NOT_SAME_DAY = "not_same_trade_date"
REASON_VERSION_MISMATCH = "calculation_version_mismatch"


@dataclass(frozen=True, slots=True)
class ResearchContext:
    """研究查询的时间上下文。

    ``asof_date`` 为空 = "取各自最新可得"（兼容既有行为），此时不判新鲜度，
    但仍逐块暴露 as-of 日期，调用方自己判断能否比较。
    """

    asof_date: date | None = None
    max_staleness_days: int | None = None
    require_same_trade_date: bool = False
    calculation_versions: dict[str, str] | None = field(default=None)

    def __post_init__(self) -> None:
        if self.max_staleness_days is not None and self.max_staleness_days < 0:
            raise ValueError("max_staleness_days 不能为负")
        if self.require_same_trade_date and self.asof_date is None:
            raise ValueError("require_same_trade_date 需要同时给出 asof_date")

    @property
    def is_latest_mode(self) -> bool:
        return self.asof_date is None


@dataclass(frozen=True, slots=True)
class BlockStatus:
    asof_date: date | None
    staleness_days: int | None
    dropped: bool
    reason: str | None = None


def evaluate_block(context: ResearchContext, block_asof: date | None) -> BlockStatus:
    """判断某个数据块在当前上下文下是否可用。"""
    if block_asof is None:
        return BlockStatus(None, None, True, REASON_MISSING)

    if context.asof_date is None:
        # 最新可得模式：不设上限，也不判新鲜度。
        return BlockStatus(block_asof, None, False, None)

    if block_asof > context.asof_date:
        # 正常情况下 SQL 已经拦住，这里是防御性判定。
        return BlockStatus(block_asof, None, True, REASON_FUTURE)

    staleness = (context.asof_date - block_asof).days
    if context.require_same_trade_date and staleness != 0:
        return BlockStatus(block_asof, staleness, True, REASON_NOT_SAME_DAY)
    if context.max_staleness_days is not None and staleness > context.max_staleness_days:
        return BlockStatus(block_asof, staleness, True, REASON_STALE)
    return BlockStatus(block_asof, staleness, False, None)


def apply_context(
    row: dict,
    context: ResearchContext,
    *,
    block_columns: dict[str, tuple[str, ...]] | None = None,
) -> dict:
    """按上下文裁剪一行研究结果，并附上每块的 as-of 与新鲜度。

    不可用块的字段被置为 ``NULL``（删除值，不是填 0），原因写进 ``stale_blocks``。
    """
    columns = block_columns or BLOCK_OUTPUT_COLUMNS
    result = dict(row)
    stale_blocks: list[str] = []

    for block in RESEARCH_BLOCKS:
        raw_asof = row.get(f"{block}_asof_date")
        block_asof = raw_asof if isinstance(raw_asof, date) else None
        status = evaluate_block(context, block_asof)

        # 口径版本不匹配的数据块同样不可用：不同公式的结果不能混在一条结论里。
        expected_version = (context.calculation_versions or {}).get(block)
        actual_version = row.get(f"{block}_calculation_version")
        if (
            not status.dropped
            and expected_version is not None
            and actual_version != expected_version
        ):
            status = BlockStatus(
                status.asof_date, status.staleness_days, True, REASON_VERSION_MISMATCH
            )

        result[f"{block}_asof_date"] = (
            status.asof_date.isoformat() if status.asof_date is not None else None
        )
        result[f"{block}_staleness_days"] = status.staleness_days

        if status.dropped:
            stale_blocks.append(f"{block}:{status.reason}")
            for column in columns.get(block, ()):
                if column in result:
                    result[column] = None

    result["research_asof_date"] = (
        context.asof_date.isoformat() if context.asof_date is not None else None
    )
    result["stale_blocks"] = stale_blocks
    result["data_quality"] = QUALITY_PASS if not stale_blocks else QUALITY_PARTIAL
    return result


def sort_key_for_aum_first(row: dict) -> tuple:
    """筛选结果的稳定排序：成交额降序、规模降序，NULL 排最后。

    与 SQL 里的 ``ORDER BY turnover_amount DESC NULLS LAST, aum DESC NULLS LAST``
    语义一致——策略在 Python 侧执行后，排序也必须跟着搬过来，否则会漏掉
    被策略置空的块。
    """
    turnover = row.get("turnover_amount")
    aum = row.get("aum")
    return (
        0 if turnover is not None else 1,
        -(turnover or 0.0),
        0 if aum is not None else 1,
        -(aum or 0.0),
    )
