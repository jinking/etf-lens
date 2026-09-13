"""按持仓权重穿透计算 ETF 的行业暴露标签。

行业知识来自 ``core.stock_industry``（由 :mod:`etf_engine.jobs.sync_industry`
从数据源同步），不再在代码里维护硬编码的股票→行业字典。

输出遵循两条诚实性要求：

1. 标签带 ``calculation_version``（口径变化必须升级版本）；
2. 标签带 ``coverage``：分类覆盖率，覆盖率不足时不给风格标签。
"""

from collections import defaultdict
from datetime import date

from etf_engine.domain.versions import TAG_VERSION
from etf_engine.repositories.stock_industry_repository import StockIndustryRepository

#: 标签计算口径版本。阈值或算法变化时必须升级。
INDUSTRY_TAGGING_VERSION = TAG_VERSION

#: 第一大行业占比达到该阈值时标记为主要行业。
PRIMARY_INDUSTRY_THRESHOLD = 0.30
#: 第二大行业占比达到该阈值时标记为次要行业。
SECONDARY_INDUSTRY_THRESHOLD = 0.18
#: 分类覆盖率低于该值时，不输出"宽基/均衡"这类风格判断。
MIN_COVERAGE_FOR_STYLE_TAG = 0.80
#: 风格标签的置信度（无额外信息，固定值并随口径版本一起记录）。
STYLE_TAG_CONFIDENCE = 0.85


class TaggingService:
    def __init__(self, repository: StockIndustryRepository | None = None):
        self.repository = repository or StockIndustryRepository()

    def calculate_industry_tags(
        self,
        etf_id: str,
        holdings: list[dict],
        asof_date: date | None = None,
        industry_map: dict[str, str] | None = None,
    ) -> list[dict]:
        """按持仓权重穿透加权，计算 ETF 的行业暴露标签。"""
        if not holdings:
            return []

        mapping = industry_map if industry_map is not None else self.repository.industry_map()

        industry_weights: dict[str, float] = defaultdict(float)
        classified_weight = 0.0
        total_weight = 0.0

        for holding in holdings:
            weight = float(holding.get("weight_pct") or 0.0)
            if weight <= 0:
                continue
            total_weight += weight
            industry = mapping.get(holding["stock_id"])
            if industry:
                industry_weights[industry] += weight
                classified_weight += weight

        if total_weight <= 0 or not industry_weights:
            return []

        coverage = classified_weight / total_weight
        sorted_industries = sorted(industry_weights.items(), key=lambda item: item[1], reverse=True)
        tags: list[dict] = []

        top1_industry, top1_weight = sorted_industries[0]
        top1_ratio = top1_weight / total_weight
        if top1_ratio >= PRIMARY_INDUSTRY_THRESHOLD:
            tags.append(
                self._tag(etf_id, top1_industry, "industry", top1_ratio, coverage, asof_date)
            )

        if len(sorted_industries) > 1:
            top2_industry, top2_weight = sorted_industries[1]
            top2_ratio = top2_weight / total_weight
            if top2_ratio >= SECONDARY_INDUSTRY_THRESHOLD:
                tags.append(
                    self._tag(etf_id, top2_industry, "industry", top2_ratio, coverage, asof_date)
                )

        # 行业分散且分类覆盖足够时，才认为是宽基/均衡配置。
        if (
            top1_ratio < PRIMARY_INDUSTRY_THRESHOLD
            and coverage >= MIN_COVERAGE_FOR_STYLE_TAG
            and len(industry_weights) >= 3
        ):
            tags.append(
                self._tag(
                    etf_id,
                    "核心宽基/均衡",
                    "style",
                    STYLE_TAG_CONFIDENCE,
                    coverage,
                    asof_date,
                )
            )

        return tags

    @staticmethod
    def _tag(
        etf_id: str,
        tag: str,
        tag_type: str,
        confidence: float,
        coverage: float,
        asof_date: date | None,
    ) -> dict:
        return {
            "etf_id": etf_id,
            "tag": tag,
            "tag_type": tag_type,
            "confidence": round(confidence, 4),
            "coverage": round(coverage, 4),
            "source": "holding_penetration",
            "calculation_version": INDUSTRY_TAGGING_VERSION,
            "valid_from": asof_date,
        }
