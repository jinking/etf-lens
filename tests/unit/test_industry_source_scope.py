from etf_engine.sources.akshare.industry import AkshareStockIndustrySource


def test_hong_kong_listings_are_out_of_scope_and_reported():
    """cninfo 是 A 股口径，港股标的必须被显式标注为"来源不适用"。"""
    source = AkshareStockIndustrySource()

    industries, issues = source.fetch_industries(["01801.HK"])

    assert industries == []
    assert [issue.rule_name for issue in issues] == ["industry_source_not_applicable"]
    assert "01801.HK" in issues[0].details
