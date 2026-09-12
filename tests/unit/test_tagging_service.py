"""行业标签必须来自数据源且带口径与覆盖率。"""

from datetime import date

from etf_engine.services.tagging_service import (
    INDUSTRY_TAGGING_VERSION,
    TaggingService,
)


class _StubRepository:
    def __init__(self, mapping: dict[str, str]):
        self._mapping = mapping

    def industry_map(self) -> dict[str, str]:
        return self._mapping


def _holdings(*weights: float) -> list[dict]:
    return [
        {"stock_id": f"{index:06d}.SZ", "stock_name": f"股票{index}", "weight_pct": weight}
        for index, weight in enumerate(weights, start=1)
    ]


def test_industry_knowledge_comes_from_the_repository_not_hardcoded_codes():
    # 同一个代码在不同数据源口径下可以是不同行业，标签只认传入的映射。
    holdings = [{"stock_id": "600519.SH", "stock_name": "贵州茅台", "weight_pct": 20.0}]
    mapping = {"600519.SH": "食品饮料"}
    service = TaggingService(_StubRepository(mapping))

    tags = service.calculate_industry_tags("510300.SH", holdings, asof_date=date(2026, 6, 30))

    assert [tag["tag"] for tag in tags] == ["食品饮料"]
    assert tags[0]["calculation_version"] == INDUSTRY_TAGGING_VERSION
    assert tags[0]["coverage"] == 1.0


def test_unmapped_stocks_do_not_produce_a_tag():
    holdings = [{"stock_id": "600519.SH", "stock_name": "贵州茅台", "weight_pct": 20.0}]
    service = TaggingService(_StubRepository({}))

    assert service.calculate_industry_tags("510300.SH", holdings) == []


def test_primary_and_secondary_industries_are_tagged_with_coverage():
    holdings = _holdings(40.0, 25.0, 5.0, 5.0)
    mapping = {
        "000001.SZ": "半导体",
        "000002.SZ": "电力设备",
        "000003.SZ": "医药生物",
    }
    service = TaggingService(_StubRepository(mapping))

    tags = service.calculate_industry_tags("588200.SH", holdings)

    assert [(tag["tag"], tag["tag_type"]) for tag in tags] == [
        ("半导体", "industry"),
        ("电力设备", "industry"),
    ]
    assert all(tag["coverage"] == 0.9333 for tag in tags)


def test_style_tag_requires_sufficient_classification_coverage():
    """分类覆盖不足时不许给出"宽基/均衡"这类风格判断。"""
    holdings = _holdings(25.0, 25.0, 25.0, 25.0)
    mapping = {"000001.SZ": "半导体", "000002.SZ": "电力设备", "000003.SZ": "医药生物"}

    low_coverage = TaggingService(_StubRepository(mapping)).calculate_industry_tags(
        "510300.SH", holdings
    )
    full_coverage = TaggingService(
        _StubRepository({**mapping, "000004.SZ": "银行"})
    ).calculate_industry_tags("510300.SH", holdings)

    # 行业标签可以带着 coverage 出现（25% 敞口是事实），但风格判断必须有覆盖支撑。
    assert [tag for tag in low_coverage if tag["tag_type"] == "style"] == []
    assert all(tag["coverage"] == 0.75 for tag in low_coverage)
    assert [tag["tag"] for tag in full_coverage if tag["tag_type"] == "style"] == ["核心宽基/均衡"]
    assert all(tag["coverage"] == 1.0 for tag in full_coverage)


def test_empty_holdings_produce_no_tags():
    assert TaggingService(_StubRepository({})).calculate_industry_tags("510300.SH", []) == []
