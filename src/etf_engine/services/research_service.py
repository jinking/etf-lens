from etf_engine.domain.identifiers import SecurityId
from etf_engine.domain.research_context import (
    ResearchContext,
    apply_context,
    sort_key_for_aum_first,
)
from etf_engine.repositories.research_repository import ResearchRepository


class ResearchService:
    """提供 ETF 批量对比 (Compare) 与条件筛选 (Screener) 统一服务。"""

    def __init__(self, repository: ResearchRepository | None = None):
        self.repository = repository or ResearchRepository()

    def compare(
        self,
        security_ids: list[str],
        context: ResearchContext | None = None,
    ) -> list[dict]:
        """按 as-of 口径对比多只 ETF。

        未传 ``context`` 时取"各自最新可得"，但每条结果仍带各块的 as-of 与新鲜度。
        """
        if not security_ids:
            return []

        canonical_ids = self._canonical_ids(security_ids)
        if not canonical_ids:
            return []
        context = context or ResearchContext()
        rows = self.repository.compare(canonical_ids, context)
        return [apply_context(row, context) for row in rows]

    def screen(
        self,
        *,
        context: ResearchContext | None = None,
        query: str | None = None,
        tag: str | None = None,
        min_aum: float | None = None,
        min_turnover_20d: float | None = None,
        min_return_20d: float | None = None,
        max_drawdown_60d: float | None = None,
        share_growth_only: bool = False,
        limit: int = 50,
    ) -> list[dict]:
        """条件筛选。

        数值条件在**新鲜度裁剪之后**判定：被判定为过期/未来的数据块字段已被置空，
        因此不可能"靠一条过期数据"通过筛选。
        """
        context = context or ResearchContext()
        candidates = self.repository.screen_candidates(
            context=context,
            query=query,
            tag=tag,
        )
        rows = [apply_context(row, context, block_columns=_SCREEN_BLOCKS) for row in candidates]

        filtered = [
            row
            for row in rows
            if _passes_filters(
                row,
                min_aum=min_aum,
                min_turnover_20d=min_turnover_20d,
                min_return_20d=min_return_20d,
                max_drawdown_60d=max_drawdown_60d,
                share_growth_only=share_growth_only,
            )
        ]
        filtered.sort(key=sort_key_for_aum_first)
        return filtered[:limit]

    def themes(
        self,
        limit: int = 50,
        min_etf_count: int = 1,
        context: ResearchContext | None = None,
    ) -> list[dict]:
        """按标签聚合主题（P2 主题聚合，同样受 as-of 约束）。"""
        return self.repository.themes(
            limit=limit,
            min_etf_count=min_etf_count,
            context=context or ResearchContext(),
        )

    @staticmethod
    def _canonical_ids(security_ids: list[str]) -> list[str]:
        canonical_ids: list[str] = []
        for security_id in security_ids:
            try:
                canonical_ids.append(SecurityId.parse(security_id).value)
            except ValueError:
                continue
        return canonical_ids


#: Screener 里各数据块对应的输出字段（规模字段叫 aum，不是 estimated_aum）。
_SCREEN_BLOCKS: dict[str, tuple[str, ...]] = {
    "quote": ("close", "change_pct", "turnover_amount"),
    "share": ("aum",),
    "metric": ("avg_turnover_amount_20d", "return_20d", "return_60d", "max_drawdown_60d"),
    "flow": ("share_change_20d", "estimated_net_subscription_20d"),
}


def _passes_filters(
    row: dict,
    *,
    min_aum: float | None,
    min_turnover_20d: float | None,
    min_return_20d: float | None,
    max_drawdown_60d: float | None,
    share_growth_only: bool,
) -> bool:
    """NULL 永远不满足条件（缺失 ≠ 通过，也 ≠ 0）。"""
    checks: list[tuple[str, float | None, str]] = [
        ("aum", min_aum, ">="),
        ("avg_turnover_amount_20d", min_turnover_20d, ">="),
        ("return_20d", min_return_20d, ">="),
        ("max_drawdown_60d", max_drawdown_60d, ">="),
    ]
    for field, threshold, _ in checks:
        if threshold is None:
            continue
        value = row.get(field)
        if value is None or value < threshold:
            return False

    if share_growth_only:
        change = row.get("share_change_20d")
        if change is None or change <= 0:
            return False
    return True
