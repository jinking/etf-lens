from datetime import datetime

import pandas as pd

from etf_engine.sources.akshare.industry import parse_industry_frames

FETCHED_AT = datetime(2026, 9, 12, 10, 0)


def _cninfo_frame(**overrides) -> pd.DataFrame:
    base = {
        "新证券简称": "比亚迪",
        "行业大类": "汽车制造业",
        "行业次类": None,
        "行业门类": "制造业",
        "行业编码": "C36",
        "分类标准": "中国上市公司协会上市公司行业分类标准",
        "证券代码": "002594",
        "变更日期": "2024-02-08",
    }
    base.update(overrides)
    return pd.DataFrame([base])


def test_prefers_csi_industry_standard():
    csi = _cninfo_frame(
        **{
            "行业大类": "乘用车",
            "行业门类": "可选消费",
            "行业编码": "25102010",
            "分类标准": "中证行业分类标准",
            "变更日期": "2021-12-17",
        }
    )
    association = _cninfo_frame()
    # cninfo 对同一只股票会把多套分类标准放在同一张表里返回。
    frame = pd.concat([csi, association], ignore_index=True)

    industries, issues = parse_industry_frames([frame], fetched_at=FETCHED_AT)

    assert issues == []
    assert len(industries) == 1
    assert industries[0].industry_name == "乘用车"
    assert industries[0].classification_standard == "中证行业分类标准"
    assert industries[0].stock_id == "002594.SZ"


def test_picks_the_latest_change_within_a_standard():
    older = _cninfo_frame(**{"行业大类": "旧行业", "变更日期": "2020-01-01"})
    newer = _cninfo_frame(**{"行业大类": "新行业", "变更日期": "2025-06-30"})
    frame = pd.concat([older, newer], ignore_index=True)

    industries, _ = parse_industry_frames([frame], fetched_at=FETCHED_AT)

    assert industries[0].industry_name == "新行业"


def test_falls_back_to_secondary_or_l1_industry_name():
    frame = _cninfo_frame(**{"行业大类": None, "行业次类": "汽车零部件"})

    industries, _ = parse_industry_frames([frame], fetched_at=FETCHED_AT)

    assert industries[0].industry_name == "汽车零部件"


def test_unknown_standard_is_reported_not_guessed():
    frame = _cninfo_frame(**{"分类标准": "某个不认识的分类"})

    industries, issues = parse_industry_frames([frame], fetched_at=FETCHED_AT)

    assert industries == []
    assert [issue.rule_name for issue in issues] == ["industry_standard_unavailable"]


def test_empty_frames_are_ignored():
    industries, issues = parse_industry_frames([pd.DataFrame()], fetched_at=FETCHED_AT)

    assert industries == []
    assert issues == []


def test_missing_code_cannot_be_parsed_into_a_fake_exchange():
    frame = _frame_with_code("999999")

    industries, issues = parse_industry_frames([frame], fetched_at=FETCHED_AT)

    assert industries == []
    assert [issue.rule_name for issue in issues] == ["industry_code_unresolved"]


def _frame_with_code(code: str) -> pd.DataFrame:
    return _cninfo_frame(**{"证券代码": code, "分类标准": "中证行业分类标准", "行业大类": "乘用车"})


def test_parse_returns_one_row_per_stock():
    frames = [_cninfo_frame(), _frame_with_code("600519")]

    industries, _ = parse_industry_frames(frames, fetched_at=FETCHED_AT)

    assert sorted(industry.stock_id for industry in industries) == ["002594.SZ", "600519.SH"]


def test_duplicate_frames_for_the_same_stock_are_not_written_twice():
    frames = [_cninfo_frame(), _cninfo_frame()]

    industries, _ = parse_industry_frames(frames, fetched_at=FETCHED_AT)

    assert [industry.stock_id for industry in industries] == ["002594.SZ"]


def test_frame_with_unexpected_shape_is_reported_not_silently_skipped():
    frame = pd.DataFrame([{"证券代码": "002594", "行业大类": "乘用车"}])

    industries, issues = parse_industry_frames([frame], fetched_at=FETCHED_AT)

    assert industries == []
    assert [issue.rule_name for issue in issues] == ["industry_frame_shape_changed"]
