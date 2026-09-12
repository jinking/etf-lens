from etf_engine.domain.identifiers import SecurityId
from etf_engine.repositories.research_repository import ResearchRepository


class ResearchService:
    """提供 ETF 批量对比 (Compare) 与条件筛选 (Screener) 统一服务。"""

    def __init__(self, repository: ResearchRepository | None = None):
        self.repository = repository or ResearchRepository()

    def compare(self, security_ids: list[str]) -> list[dict]:
        if not security_ids:
            return []

        canonical_ids = self._canonical_ids(security_ids)
        if not canonical_ids:
            return []
        return self.repository.compare(canonical_ids)

    def screen(
        self,
        *,
        query: str | None = None,
        tag: str | None = None,
        min_aum: float | None = None,
        min_turnover_20d: float | None = None,
        min_return_20d: float | None = None,
        max_drawdown_60d: float | None = None,
        share_growth_only: bool = False,
        limit: int = 50,
    ) -> list[dict]:
        return self.repository.screen(
            query=query,
            tag=tag,
            min_aum=min_aum,
            min_turnover_20d=min_turnover_20d,
            min_return_20d=min_return_20d,
            max_drawdown_60d=max_drawdown_60d,
            share_growth_only=share_growth_only,
            limit=limit,
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
