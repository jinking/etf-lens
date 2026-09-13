"""`etf screen` 的行为基线（筛选口径 + 排序）。"""

from etf_engine.services.research_service import ResearchService

SCREEN_CONTRACT = [
    "security_id",
    "fund_name",
    "manager_name",
    "fund_type",
    "close",
    "change_pct",
    "turnover_amount",
    "avg_turnover_amount_20d",
    "aum",
    "return_20d",
    "return_60d",
    "max_drawdown_60d",
    "share_change_20d",
    "estimated_net_subscription_20d",
    "tags",
    "tracking_index_name",
    "tracking_index_pit",
    "quote_asof_date",
    "share_asof_date",
    "metric_asof_date",
    "flow_asof_date",
    "metric_calculation_version",
    "flow_calculation_version",
    "quote_staleness_days",
    "share_staleness_days",
    "metric_staleness_days",
    "flow_staleness_days",
    "research_asof_date",
    "stale_blocks",
    "data_quality",
]


def test_screen_output_contract_is_frozen(warehouse):
    rows = ResearchService().screen(limit=10)

    assert list(rows[0]) == SCREEN_CONTRACT


def test_screen_without_filters_orders_by_aum(warehouse):
    """三只 ETF 成交额相同，因此规模决定次序（159919 > 510300 > 588200）。"""
    rows = ResearchService().screen(limit=10)

    assert [row["security_id"] for row in rows] == ["159919.SZ", "510300.SH", "588200.SH"]
    assert [row["aum"] for row in rows] == [3720.0, 1860.0, 930.0]


def test_screen_filters_by_tag(warehouse):
    rows = ResearchService().screen(tag="集成电路")

    assert [row["security_id"] for row in rows] == ["588200.SH"]
    assert rows[0]["tags"] == "集成电路"


def test_screen_filters_by_aum_and_share_growth(warehouse):
    big = ResearchService().screen(min_aum=2000)
    growing = ResearchService().screen(share_growth_only=True)

    assert [row["security_id"] for row in big] == ["159919.SZ"]
    assert len(growing) == 3, "三只 ETF 的 20 日份额都在增长"


def test_screen_limit_is_respected(warehouse):
    assert len(ResearchService().screen(limit=2)) == 2
