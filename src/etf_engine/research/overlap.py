"""持仓重合度：回答"两只 ETF 看起来不同，实际上是不是高度重复？"

四种口径分开给，不合成一个分数：

```text
holding_overlap_ratio   共同持仓只数 / 较少一方只数
weighted_overlap        共同持仓上 min(权重A, 权重B) 之和（更接近真实重复敞口）
top10_overlap           前十大重合只数 / 10
industry_overlap        行业维度：Σ min(权重A_行业, 权重B_行业)
```
"""

from collections import defaultdict
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class OverlapResult:
    holding_overlap_ratio: float | None
    weighted_overlap: float | None
    top10_overlap: float | None
    industry_overlap: float | None
    common_holdings: list[str]


def _weights(holdings: list[dict]) -> dict[str, float]:
    result: dict[str, float] = {}
    for holding in holdings:
        stock_id = str(holding.get("stock_id") or "").strip()
        if not stock_id:
            continue
        weight = holding.get("weight_pct")
        result[stock_id] = float(weight) if weight is not None else 0.0
    return result


def holding_overlap(holdings_a: list[dict], holdings_b: list[dict]) -> OverlapResult:
    weights_a = _weights(holdings_a)
    weights_b = _weights(holdings_b)
    if not weights_a or not weights_b:
        return OverlapResult(None, None, None, None, [])

    common = sorted(set(weights_a) & set(weights_b))
    smaller = min(len(weights_a), len(weights_b))
    ratio = len(common) / smaller if smaller else None
    weighted = sum(min(weights_a[code], weights_b[code]) for code in common)

    top_a = sorted(weights_a, key=lambda code: weights_a[code], reverse=True)[:10]
    top_b = sorted(weights_b, key=lambda code: weights_b[code], reverse=True)[:10]
    top_overlap = len(set(top_a) & set(top_b)) / 10 if top_a and top_b else None

    return OverlapResult(ratio, weighted, top_overlap, None, common)


def industry_overlap(weights_a: dict[str, float], weights_b: dict[str, float]) -> float | None:
    """行业权重向量的重合度：Σ min(A_行业, B_行业)。"""
    if not weights_a or not weights_b:
        return None
    industries = set(weights_a) | set(weights_b)
    return sum(
        min(weights_a.get(industry, 0.0), weights_b.get(industry, 0.0)) for industry in industries
    )


def industry_weights(holdings: list[dict], industry_map: dict[str, str]) -> dict[str, float]:
    """按行业聚合持仓权重；未分类的持仓计入 ``__unclassified__``（不丢样本）。"""
    result: dict[str, float] = defaultdict(float)
    for code, weight in _weights(holdings).items():
        result[industry_map.get(code, "__unclassified__")] += weight
    return dict(result)
