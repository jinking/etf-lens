"""同类比较与持仓重合度的应用服务（Compare 的研究维度 + 重叠分析）。"""

from datetime import date

from etf_engine.domain.identifiers import SecurityId
from etf_engine.repositories.holding_repository import HoldingRepository
from etf_engine.repositories.peer_repository import PeerRepository
from etf_engine.repositories.stock_industry_repository import StockIndustryRepository
from etf_engine.research.overlap import holding_overlap, industry_overlap, industry_weights

#: Compare 的五个研究维度（不含综合评分，也不含买卖建议）。
RESEARCH_DIMENSIONS: tuple[str, ...] = (
    "基础规模",
    "流动性",
    "跟踪质量",
    "成本",
    "资金与拥挤度",
)


def _canonical(security_id: str) -> str | None:
    try:
        return SecurityId.parse(security_id).value
    except ValueError:
        return None


class PeerService:
    def __init__(
        self,
        repository: PeerRepository | None = None,
        holding_repository: HoldingRepository | None = None,
        industry_repository: StockIndustryRepository | None = None,
    ):
        self.repository = repository or PeerRepository()
        self.holdings = holding_repository or HoldingRepository()
        self.industries = industry_repository or StockIndustryRepository()

    def compare_peers(self, security_ids: list[str], asof_date: date | None = None) -> list[dict]:
        """按五个研究维度给出同类分位（数据缺失的维度如实为 null）。"""
        rows: list[dict] = []
        for security_id in security_ids:
            canonical = _canonical(security_id)
            if canonical is None:
                continue
            group = self.repository.group_of(canonical)
            peers = self.repository.peers_of(canonical, asof_date=asof_date)
            rows.append(
                {
                    "security_id": canonical,
                    "peer_group_id": (peers or group or {}).get("peer_group_id"),
                    "peer_group_kind": (group or {}).get("peer_group_kind"),
                    "peer_count": (peers or group or {}).get("peer_count"),
                    "asof_date": (peers or {}).get("asof_date"),
                    "dimensions": {
                        "基础规模": {"aum_rank_pct": (peers or {}).get("aum_rank_pct")},
                        "流动性": {"turnover_rank_pct": (peers or {}).get("turnover_rank_pct")},
                        "跟踪质量": {
                            "tracking_error_rank_pct": (peers or {}).get("tracking_error_rank_pct")
                        },
                        "成本": {"fee_rank_pct": (peers or {}).get("fee_rank_pct")},
                        "资金与拥挤度": {
                            "flow_rank_pct": (peers or {}).get("flow_rank_pct"),
                            "premium_stability_rank_pct": (peers or {}).get(
                                "premium_stability_rank_pct"
                            ),
                        },
                    },
                }
            )
        return rows

    def tracking_quality(
        self, security_ids: list[str], asof_date: date | None = None
    ) -> list[dict]:
        """只看跟踪质量维度（跟踪误差分位 + 同类样本量）。"""
        return [
            {
                "security_id": row["security_id"],
                "peer_group_id": row["peer_group_id"],
                "peer_count": row["peer_count"],
                "tracking_error_rank_pct": row["dimensions"]["跟踪质量"]["tracking_error_rank_pct"],
            }
            for row in self.compare_peers(security_ids, asof_date=asof_date)
        ]

    def exposure_overlap(self, security_ids: list[str]) -> dict:
        """两两持仓重合度；行业维度用统一的行业分类口径。"""
        holdings: dict[str, list[dict]] = {}
        for security_id in security_ids:
            canonical = _canonical(security_id)
            if canonical is None:
                continue
            top, _ = self.holdings.get_latest_top10(canonical)
            holdings[canonical] = top

        industry_map = self.industries.industry_map()
        pairs: list[dict] = []
        codes = sorted(holdings)
        for index, left in enumerate(codes):
            for right in codes[index + 1 :]:
                result = holding_overlap(holdings[left], holdings[right])
                pairs.append(
                    {
                        "left": left,
                        "right": right,
                        "holding_overlap_ratio": result.holding_overlap_ratio,
                        "weighted_overlap": result.weighted_overlap,
                        "top10_overlap": result.top10_overlap,
                        "industry_overlap": industry_overlap(
                            industry_weights(holdings[left], industry_map),
                            industry_weights(holdings[right], industry_map),
                        ),
                        "common_holdings": result.common_holdings,
                    }
                )
        return {
            "coverage": {security_id: len(items) for security_id, items in holdings.items()},
            "pairs": pairs,
        }
