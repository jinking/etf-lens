"""实验版看盘规则（``pulse_v3_experimental``）：把输入换成标准化序列。

与 ``pulse_v2`` 的唯一差别是**输入的尺度**：

```text
pulse_v2  两融余额、成交额的绝对水平（250 日分位 → 受市场扩容影响）
pulse_v3  两融/流通市值、成交额/流通市值（分位 → 跨期可比）
```

阈值与状态机完全沿用 v2（同一条规则换输入），因此两者差异**只**来自"绝对水平
随年份抬升"这一件事——这正是我们要量化的。

约束：

* 不替换 ``pulse_v2``，也不写入 ``mart.market_pulse_daily``（那是 v2 的表）；
* 不做阈值寻优（升级方案 §6.3）；
* 标准化序列缺失时不退回绝对值——退回就等于掩盖"标准化不可得"，直接给 UNKNOWN。
"""

from dataclasses import dataclass

from etf_engine.domain.versions import PULSE_V3_EXPERIMENTAL_VERSION
from etf_engine.research.market_pulse import (
    LayerResult,
    LayerState,
    evaluate_liquidity,
    evaluate_volume,
    overall_state,
)

VERSION = PULSE_V3_EXPERIMENTAL_VERSION


@dataclass(frozen=True, slots=True)
class PulseV3Result:
    liquidity: LayerResult
    volume: LayerResult
    overall: str
    strong_layers: int
    known_layers: int
    calculation_version: str = VERSION


def _as_rows(norm_rows: list[dict], *, field: str) -> list[dict]:
    """把标准化序列包装成 v2 评分函数认识的形状。"""
    return [{"trade_date": row.get("trade_date"), field: row.get("value")} for row in norm_rows]


def evaluate_liquidity_v3(norm_rows: list[dict]) -> LayerResult:
    """第一层：标准化两融（两融余额 / 流通市值）。"""
    usable = [row for row in norm_rows if row.get("value") is not None]
    if len(usable) < 6:
        return LayerResult(
            LayerState.UNKNOWN,
            0,
            f"标准化两融序列不足（{len(usable)} 个交易日，至少需要 6 个）",
            {"margin_balance_ratio": usable[-1]["value"] if usable else None},
        )
    result = evaluate_liquidity(_as_rows(norm_rows, field="margin_balance_total"))
    metrics = dict(result.metrics)
    metrics["margin_balance_ratio"] = usable[-1]["value"]
    return LayerResult(result.state, result.score, result.note, metrics)


def evaluate_volume_v3(norm_rows: list[dict]) -> LayerResult:
    """第二层：标准化量能（成交额 / 流通市值）。

    注意量比（当日 / 前 5 日均值）本身是比值，标准化前后不变；
    变化的是"位置分位"的参照系。
    """
    usable = [row for row in norm_rows if row.get("value") is not None]
    if len(usable) < 6:
        return LayerResult(
            LayerState.UNKNOWN,
            0,
            f"标准化成交额序列不足（{len(usable)} 个交易日，至少需要 6 个）",
            {"turnover_ratio": usable[-1]["value"] if usable else None},
        )
    result = evaluate_volume(_as_rows(norm_rows, field="turnover_amount_total"))
    metrics = dict(result.metrics)
    metrics["turnover_ratio"] = usable[-1]["value"]
    return LayerResult(result.state, result.score, result.note, metrics)


def evaluate_v3(
    *,
    margin_norm: list[dict],
    turnover_norm: list[dict],
    etf_layer: LayerResult,
) -> PulseV3Result:
    """两层标准化 + 沿用 v2 的 ETF 层，给出实验版结论（不落库）。"""
    liquidity = evaluate_liquidity_v3(margin_norm)
    volume = evaluate_volume_v3(turnover_norm)
    overall, strong, known = overall_state(
        {
            "liquidity": liquidity.state,
            "volume": volume.state,
            "etf": etf_layer.state,
        }
    )
    return PulseV3Result(liquidity, volume, overall.value, strong, known)
