from dataclasses import dataclass


@dataclass(slots=True)
class ReconcileResult:
    value: float | None
    quality_status: str
    source_values: dict[str, float | None]


def reconcile_numeric(
    source_values: dict[str, float | None],
    *,
    tolerance_ratio: float = 0.001,
) -> ReconcileResult:
    """最小数值对账器。

    V1 只提供基础能力；具体字段阈值后续按 dataset 配置。
    """
    present = {k: v for k, v in source_values.items() if v is not None}
    if not present:
        return ReconcileResult(None, "FAILED", source_values)

    if len(present) == 1:
        value = next(iter(present.values()))
        return ReconcileResult(value, "PASS", source_values)

    values = list(present.values())
    base = values[0]
    if base == 0:
        equal = all(v == 0 for v in values)
    else:
        equal = all(abs(v - base) / abs(base) <= tolerance_ratio for v in values[1:])

    if equal:
        return ReconcileResult(base, "VERIFIED", source_values)

    return ReconcileResult(None, "CONFLICT", source_values)
