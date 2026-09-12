"""新发基金适配器与月度聚合的口径测试。

这一层的坑都在"单位"和"缺失"上：

* 募集份额单位是**亿元**，不能和成交额（元）混用；
* 缺失募集份额的行要保留 NULL，不能在月度合计里当 0；
* 没有成立日期的行照常入库，但不参与月度聚合。
"""

from datetime import date, datetime
from decimal import Decimal

import pandas as pd

from etf_engine.sources.akshare.fund_issuance import parse_fund_issuance_frame

FETCHED_AT = datetime(2026, 9, 12, 10, 0)


def _frame() -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "基金代码": "028813",
                "基金简称": "某消费混合A",
                "发行公司": "某基金",
                "基金类型": "混合型-偏股",
                "集中认购期": "26/08/26～26/08/26",
                "募集份额": 0.10,
                "成立日期": "2026-08-28",
                "成立来涨幅": -0.87,
                "基金经理": "张三",
                "申购状态": "开放申购",
                "优惠费率": 0.08,
            },
            {
                "基金代码": "028814",
                "基金简称": "某债基C",
                "发行公司": "某基金",
                "基金类型": "债券型-长债",
                "集中认购期": "26/08/20～26/08/26",
                "募集份额": None,  # 上游未披露
                "成立日期": "2026-08-28",
                "成立来涨幅": 0.01,
                "基金经理": "李四",
                "申购状态": "开放申购",
                "优惠费率": 0.00,
            },
            {
                "基金代码": "000001",
                "基金简称": "未成立基金",
                "发行公司": "某基金",
                "基金类型": "股票型",
                "集中认购期": "26/09/01～26/09/20",
                "募集份额": None,
                "成立日期": None,  # 还没成立
                "成立来涨幅": None,
                "基金经理": "王五",
                "申购状态": "认购期",
                "优惠费率": None,
            },
        ]
    )


def test_parse_keeps_missing_shares_as_null():
    rows, issues = parse_fund_issuance_frame(_frame(), fetched_at=FETCHED_AT)

    assert issues == []
    assert len(rows) == 3
    by_code = {row.fund_code: row for row in rows}
    assert by_code["028813"].raised_shares == Decimal("0.10")
    # 未知 ≠ 0：未披露保持 NULL
    assert by_code["028814"].raised_shares is None
    assert by_code["028814"].established_date == date(2026, 8, 28)
    # 没有成立日期的行照常入库，供后续回填
    assert by_code["000001"].established_date is None


def test_parse_rejects_rows_without_code():
    frame = _frame()
    frame.loc[0, "基金代码"] = None
    rows, issues = parse_fund_issuance_frame(frame, fetched_at=FETCHED_AT)

    assert len(rows) == 2
    assert issues and issues[0].rule_name == "fund_issuance_code_missing"


def test_parse_requires_established_date_column():
    frame = _frame().drop(columns=["成立日期"])
    try:
        parse_fund_issuance_frame(frame, fetched_at=FETCHED_AT)
    except RuntimeError as exc:
        assert "成立日期" in str(exc)
    else:  # pragma: no cover - 缺列必须显式失败
        raise AssertionError("缺列时应当报错")
