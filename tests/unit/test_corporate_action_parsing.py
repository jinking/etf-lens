"""公司行为解析：只认披露表，占位行不算数据。"""

from datetime import date, datetime
from decimal import Decimal

from etf_engine.domain.enums import CorporateActionType
from etf_engine.sources.akshare.corporate_action import parse_corporate_action_tables

FETCHED_AT = datetime(2026, 9, 12, 18, 0)

#: 取自真实页面结构：分红表为空时只有一行占位文本。
EMPTY_DIVIDEND_HTML = """
<table><tr><th>年份</th><th>权益登记日</th><th>除息日</th><th>每10份分红</th>
<th>分红发放日</th></tr><tr><td>暂无分红信息!</td></tr></table>
<table><tr><th>年份</th><th>拆分折算日</th><th>拆分类型</th><th>拆分折算比例</th></tr>
<tr><td>2026年</td><td>2026-07-03</td><td>份额分拆</td><td>1:2.0000</td></tr>
<tr><td>2026年</td><td>2026-02-02</td><td>份额分拆</td><td>1:3.0000</td></tr></table>
"""

DIVIDEND_HTML = """
<table><tr><th>年份</th><th>权益登记日</th><th>除息日</th><th>每10份分红</th>
<th>分红发放日</th></tr>
<tr><td>2026年</td><td>2026-01-16</td><td>2026-01-19</td>
<td>每10份派现金1.2300元</td><td>2026-01-27</td></tr></table>
"""


def test_placeholder_row_is_skipped_not_parsed():
    actions, issues = parse_corporate_action_tables(
        EMPTY_DIVIDEND_HTML, security_id="515880.SH", fetched_at=FETCHED_AT
    )

    assert issues == []
    assert [action.action_type for action in actions] == [
        CorporateActionType.SPLIT,
        CorporateActionType.SPLIT,
    ]


def test_split_ratio_becomes_share_and_nav_factors():
    actions, _ = parse_corporate_action_tables(
        EMPTY_DIVIDEND_HTML, security_id="515880.SH", fetched_at=FETCHED_AT
    )

    # 结果按日期升序：先 2026-02-02（1:3），后 2026-07-03（1:2）
    first = next(action for action in actions if action.action_date == date(2026, 7, 3))
    assert first.split_ratio == "1:2.0000"
    assert first.share_adjustment_factor == Decimal(2)
    assert first.nav_adjustment_factor == Decimal("0.5")


def test_dividend_cash_is_per_unit_not_per_ten_units():
    actions, _ = parse_corporate_action_tables(
        DIVIDEND_HTML, security_id="510300.SH", fetched_at=FETCHED_AT
    )

    assert len(actions) == 1
    dividend = actions[0]
    assert dividend.action_type is CorporateActionType.DIVIDEND
    assert dividend.action_date == date(2026, 1, 19), "用除息日，不是权益登记日"
    assert dividend.cash_distribution == Decimal("0.123")


def test_actions_are_sorted_by_date():
    actions, _ = parse_corporate_action_tables(
        DIVIDEND_HTML + EMPTY_DIVIDEND_HTML,
        security_id="510300.SH",
        fetched_at=FETCHED_AT,
    )

    dates = [action.action_date for action in actions]
    assert dates == sorted(dates)
