"""上游 shape 变化必须变成质量记录，而不是 KeyError 或静默跳过。"""

import pandas as pd

from etf_engine.ingestion.contracts import FrameContract, check_frame

CONTRACT = FrameContract("demo_dataset", ("基金代码", "单位净值"))


def test_missing_required_column_is_reported_as_schema_change():
    frame = pd.DataFrame([{"基金代码": "510300"}])

    usable, issues = check_frame(frame, CONTRACT)

    assert usable is False
    assert [issue.rule_name for issue in issues] == ["demo_dataset_schema_changed"]
    assert issues[0].severity == "ERROR"
    assert "单位净值" in issues[0].details


def test_empty_response_is_an_error_by_default():
    usable, issues = check_frame(pd.DataFrame(), CONTRACT)

    assert usable is False
    assert issues[0].rule_name == "demo_dataset_empty_response"
    assert issues[0].severity == "ERROR"


def test_empty_response_can_be_tolerated_as_a_warning():
    contract = FrameContract("demo_dataset", ("基金代码",), allow_empty=True)

    usable, issues = check_frame(pd.DataFrame(), contract)

    assert usable is False
    assert issues[0].severity == "WARN", "允许为空的来源只记 WARN"


def test_none_response_is_reported():
    usable, issues = check_frame(None, CONTRACT)

    assert usable is False
    assert issues[0].rule_name == "demo_dataset_response_none"


def test_conforming_frame_passes_without_issues():
    frame = pd.DataFrame([{"基金代码": "510300", "单位净值": 1.0}])

    usable, issues = check_frame(frame, CONTRACT)

    assert usable is True
    assert issues == []


def test_nav_adapter_reports_schema_change_instead_of_crashing(monkeypatch):
    """净值接口换了列名 → 产出质量问题，而不是 KeyError。"""
    from etf_engine.sources.akshare import nav as nav_module

    monkeypatch.setattr(
        nav_module.ak, "fund_etf_fund_daily_em", lambda: pd.DataFrame([{"代码": "510300"}])
    )

    navs, issues = nav_module.AkshareETFNavSource().fetch_navs_with_issues()

    assert navs == []
    assert [issue.rule_name for issue in issues] == ["etf_nav_daily_schema_changed"]
