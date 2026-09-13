"""MCP 工具层：与 REST API 共用同一套 Application Service。

约束（见 ``docs/TECHNICAL.md`` §11）：

- 不直接执行任意 SQL；
- 不直接调用 AKShare；
- 不写 Core Facts。

这里只做"参数 → 服务 → 可序列化结果"的编排，因此不依赖 MCP SDK，
可以直接单测；真正的 transport 在 :mod:`etf_engine.mcp.server`。
"""

from collections.abc import Callable
from datetime import date
from typing import Any

from etf_engine.domain.identifiers import SecurityId
from etf_engine.domain.research_context import ResearchContext
from etf_engine.repositories.holding_repository import HoldingRepository
from etf_engine.repositories.mart_repository import MartRepository
from etf_engine.repositories.master_repository import MasterRepository
from etf_engine.repositories.tag_repository import TagRepository
from etf_engine.services.core_metrics_service import ETFCoreMetricsService
from etf_engine.services.etf_service import ETFService
from etf_engine.services.peer_service import PeerService
from etf_engine.services.research_service import ResearchService
from etf_engine.services.watchboard_service import WatchboardService


def _canonical(security_id: str) -> str:
    return SecurityId.parse(security_id).value


def search_etfs(query: str | None = None, limit: int = 20) -> list[dict]:
    """按代码或名称搜索 ETF，返回本地最新行情。"""
    return ETFService().search_etfs(query=query, limit=limit)


def get_etf_profile(security_id: str) -> dict:
    """ETF 档案：基本信息 + 跟踪指数 + 行业标签。"""
    canonical = _canonical(security_id)
    profile = ETFService().get_latest_snapshot(canonical)
    profile["master"] = MasterRepository().get_by_id(canonical)
    profile["tags"] = TagRepository().get_tags(canonical)
    return profile


def get_etf_quote(security_id: str) -> dict:
    """ETF 最新行情快照。"""
    return ETFService().get_latest_snapshot(_canonical(security_id))


def get_etf_performance(security_id: str) -> dict:
    """收益 / 波动率 / 回撤 / 流动性等派生指标。"""
    canonical = _canonical(security_id)
    metrics = MartRepository().get_latest_metrics(canonical)
    if metrics is None:
        raise LookupError(f"本地尚未计算 {canonical} 的研究指标")
    return metrics


def get_etf_flow(security_id: str) -> dict:
    """份额变化与估算申赎资金。

    估算值带 ``is_estimated`` 与 ``calculation_version``，缺失时字段为 null。
    """
    canonical = _canonical(security_id)
    flow = MartRepository().get_latest_flow(canonical)
    if flow is None:
        raise LookupError(f"本地尚未计算 {canonical} 的资金指标")
    return flow


def get_etf_holdings(security_id: str) -> dict:
    """最近一期披露的前十大持仓。"""
    canonical = _canonical(security_id)
    holdings, report_date = HoldingRepository().get_latest_top10(canonical)
    return {
        "security_id": canonical,
        "report_date": report_date.isoformat() if report_date else None,
        # 披露持仓不是实时组合，调用方必须看报告期。
        "holdings": holdings,
    }


def compare_etfs(
    security_ids: list[str],
    asof_date: date | None = None,
    max_staleness_days: int | None = None,
) -> list[dict]:
    """同一 as-of 口径下对比多只 ETF。

    ``asof_date`` 为 Point-in-Time 截止日：只使用当天（含）之前的数据，
    并对每个数据块返回其真实 as-of 与滞后天数。
    """
    context = ResearchContext(asof_date=asof_date, max_staleness_days=max_staleness_days)
    return ResearchService().compare(security_ids, context)


def screen_etfs(
    asof_date: date | None = None,
    max_staleness_days: int | None = None,
    query: str | None = None,
    tag: str | None = None,
    min_aum: float | None = None,
    min_turnover_20d: float | None = None,
    min_return_20d: float | None = None,
    max_drawdown_60d: float | None = None,
    share_growth_only: bool = False,
    limit: int = 50,
) -> list[dict]:
    """按条件筛选 ETF（数据库筛选，不是大模型遍历）。"""
    return ResearchService().screen(
        context=ResearchContext(asof_date=asof_date, max_staleness_days=max_staleness_days),
        query=query,
        tag=tag,
        min_aum=min_aum,
        min_turnover_20d=min_turnover_20d,
        min_return_20d=min_return_20d,
        max_drawdown_60d=max_drawdown_60d,
        share_growth_only=share_growth_only,
        limit=limit,
    )


def get_core_metrics(security_id: str, asof_date: date | None = None) -> dict:
    """核心研究指标（含缺失去因说明）。"""
    metrics = ETFCoreMetricsService().get_core_metrics(security_id, asof_date)
    return metrics.model_dump(mode="json")


def get_market_pulse(asof_date: date | None = None) -> dict:
    """三层看盘状态（流动性 / 量能 / 宽基 ETF）。

    返回的是**确定性规则引擎**（``pulse_v2``）的状态标签，不是观点，
    也不构成投资建议；每层附带覆盖度与缺口说明（见 docs/WATCHBOARD.md）。
    """
    payload = WatchboardService().watchboard(asof_date=asof_date)
    # 序列化给 Agent 时不带整段成交额/两融序列（那是界面画图用的），
    # 只给判定所需的事实与口径说明。
    payload.pop("turnover_series", None)
    payload.pop("margin_series", None)
    return payload


def compare_peer_etfs(security_ids: list[str], asof_date: date | None = None) -> list[dict]:
    """同类比较：五个研究维度（基础规模/流动性/跟踪质量/成本/资金与拥挤度）。"""
    return PeerService().compare_peers(security_ids, asof_date=asof_date)


def get_tracking_quality(security_ids: list[str], asof_date: date | None = None) -> list[dict]:
    """跟踪质量：同类中的跟踪误差分位（数值越低越好 → 分位越高越好）。"""
    return PeerService().tracking_quality(security_ids, asof_date=asof_date)


def compare_exposure_overlap(security_ids: list[str]) -> dict:
    """持仓重合度：判断两只 ETF 是否高度重复。"""
    return PeerService().exposure_overlap(security_ids)


TOOL_FUNCTIONS: dict[str, Callable[..., Any]] = {
    "search_etfs": search_etfs,
    "get_etf_profile": get_etf_profile,
    "get_etf_quote": get_etf_quote,
    "get_etf_performance": get_etf_performance,
    "get_etf_flow": get_etf_flow,
    "get_etf_holdings": get_etf_holdings,
    "compare_etfs": compare_etfs,
    "screen_etfs": screen_etfs,
    "get_market_pulse": get_market_pulse,
    "compare_peer_etfs": compare_peer_etfs,
    "get_tracking_quality": get_tracking_quality,
    "compare_exposure_overlap": compare_exposure_overlap,
}
