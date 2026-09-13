"""同类分组与同类分位。

分组优先级（确定性，且不许用名称模糊匹配）：

```text
1. 同一 tracking_index_id          （基金披露的跟踪指数，最强依据）
2. 同一基准身份（tracking_index_name）  （拿不到代码时的等价物）
3. 同一主标签                       （仅兜底：以上都没有时才用）
```

分位统一成"越大越好"：费用与跟踪误差这类"越低越好"的指标取反向分位，
方向表写在 :data:`RANK_DIRECTIONS` 里，避免读的人自己去猜。
"""

from dataclasses import dataclass

PEER_CALCULATION_VERSION = "peer_v1"

#: 分组依据的种类。
KIND_TRACKING_INDEX = "tracking_index"
KIND_BENCHMARK_NAME = "benchmark_name"
KIND_TAG = "tag"

#: 指标方向：True = 数值越大越好（分位直接取数值分位），False = 取反向分位。
RANK_DIRECTIONS: dict[str, bool] = {
    "aum": True,
    "turnover": True,
    "flow": True,
    "tracking_error": False,
    "fee": False,
    "premium_stability": False,
}

#: 同类样本少于该数量时不产分位——3 只以下的"同类第一"没有意义。
MIN_PEER_COUNT = 3


@dataclass(frozen=True, slots=True)
class PeerGroup:
    security_id: str
    peer_group_id: str
    kind: str
    label: str | None


def assign_peer_group(
    *,
    security_id: str,
    tracking_index_id: str | None = None,
    tracking_index_name: str | None = None,
    primary_tag: str | None = None,
) -> PeerGroup | None:
    """给一只 ETF 判定同类分组；三条依据都缺时返回 None（不猜）。"""
    if tracking_index_id:
        return PeerGroup(
            security_id, f"index:{tracking_index_id}", KIND_TRACKING_INDEX, tracking_index_id
        )
    if tracking_index_name:
        return PeerGroup(
            security_id,
            f"benchmark:{tracking_index_name}",
            KIND_BENCHMARK_NAME,
            tracking_index_name,
        )
    if primary_tag:
        return PeerGroup(security_id, f"tag:{primary_tag}", KIND_TAG, primary_tag)
    return None


def percentile(
    values: list[float | None], value: float | None, *, higher_is_better: bool
) -> float | None:
    """值在同类样本中的分位（0..1，已统一成"越大越好"）。

    定义：``分位 = 比我差的同类只数 / (同类只数 − 1)``，因此

    ```text
    最好 → 1.0      最差 → 0.0      并列 → 同分
    ```

    两个方向共用同一把尺子：``higher_is_better=False``（费用、跟踪误差）时，
    "比我差的"指数值比我大的人。这样 1.0 恒定代表同类最优，读的人不必再记方向。
    样本不足（少于 :data:`MIN_PEER_COUNT`）时返回 None。
    """
    if value is None:
        return None
    present = [item for item in values if item is not None]
    if len(present) < MIN_PEER_COUNT:
        return None
    worse = sum(1 for item in present if (item < value if higher_is_better else item > value))
    return worse / (len(present) - 1)


def group_members(groups: list[PeerGroup]) -> dict[str, list[str]]:
    """``{peer_group_id: [security_id, ...]}``，顺序稳定。"""
    members: dict[str, list[str]] = {}
    for group in groups:
        members.setdefault(group.peer_group_id, []).append(group.security_id)
    return {key: sorted(value) for key, value in sorted(members.items())}
