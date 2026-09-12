"""ETF 跟踪指数对齐必须是事实匹配，不能靠"看起来最像"。"""

from etf_engine.ingestion.index_matcher import match_index, normalize_index_name

CATALOG = {
    "000300": ["沪深300指数", "沪深300"],
    "931160": ["中证全指通信设备指数", "通信设备"],
    "931743": ["中证半导体材料设备主题指数", "半导体材料设备"],
    "399006": ["创业板指", "创业板指数"],
    "000852": ["中证1000指数", "中证1000"],
}


def test_normalize_strips_decorations_and_separators():
    assert normalize_index_name("沪深 300 指数收益率") == "沪深300指数"
    assert normalize_index_name("中证全指通信设备指数收益率") == "中证全指通信设备指数"


def test_matches_exact_benchmark_text():
    matched = match_index("中证全指通信设备指数收益率", CATALOG)

    assert matched is not None
    assert matched.index_id == "931160"


def test_matches_short_name_in_catalog():
    matched = match_index("创业板指数收益率", CATALOG)

    assert matched is not None
    assert matched.index_id == "399006"


def test_unknown_benchmark_returns_none_instead_of_best_guess():
    assert match_index("某个不存在的主题指数收益率", CATALOG) is None


def test_ambiguous_benchmark_returns_none():
    """基准里同时命中多条指数时不能随便挑一条。"""
    catalog = {
        "000300": ["沪深300指数"],
        "399300": ["沪深300指数"],
    }

    assert match_index("沪深300指数收益率", catalog) is None


def test_too_short_catalog_names_do_not_produce_false_matches():
    catalog = {"000001": ["上证"], "000002": ["深证"]}

    assert match_index("上证综指收益率", catalog) is None


def test_empty_benchmark_returns_none():
    assert match_index("", CATALOG) is None
