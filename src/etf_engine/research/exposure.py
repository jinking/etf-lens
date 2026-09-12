from dataclasses import dataclass

from etf_engine.domain.core_metrics import HoldingItem


@dataclass(frozen=True, slots=True)
class ExposureMetrics:
    holdings: list[HoldingItem]
    concentration: float | None
    reason: str | None = None


def calculate_top10_concentration(holdings: list[dict]) -> ExposureMetrics:
    """Normalize either fractional or percentage weights without guessing mixed units."""
    prepared: list[tuple[dict, float]] = []
    for holding in holdings:
        weight = holding.get("weight_pct")
        if weight is None:
            continue
        prepared.append((holding, float(weight)))

    prepared.sort(key=lambda item: item[1], reverse=True)
    top10 = prepared[:10]
    if not top10:
        return ExposureMetrics([], None, "holding_weights_unavailable")

    raw_total = sum(weight for _, weight in prepared)
    raw_sum = sum(weight for _, weight in top10)
    percentage_scale = 100.0 if any(weight > 1.05 for _, weight in prepared) else 1.0
    maximum_total = 105.0 if percentage_scale == 100.0 else 1.05
    if any(weight < 0 for _, weight in prepared) or raw_total > maximum_total:
        return ExposureMetrics([], None, "holding_weight_conflict")

    normalized = [
        HoldingItem(
            stock_id=str(holding["stock_id"]),
            stock_name=holding.get("stock_name"),
            weight_pct=weight / percentage_scale,
        )
        for holding, weight in top10
    ]
    return ExposureMetrics(normalized, raw_sum / percentage_scale)
