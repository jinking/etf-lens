from datetime import date
from decimal import Decimal

from etf_engine.sources.akshare.fund_profile import parse_fund_profile

#: 取自真实基金概况页的结构：表格里一行放两组 th/td，前面还有 label/span 的成立日期。
PROFILE_HTML = """
<html><body>
<div class="bs_gl"><p>
  <label>成立日期：<span>2022-09-30</span></label>
  <label>基金经理：&nbsp;&nbsp;<a href="#">田光远</a></label>
</p></div>
<table>
  <tr><th>基金全称</th><td>嘉实上证科创板芯片交易型开放式指数证券投资基金</td></tr>
  <tr><th>基金简称</th><td>科创芯片ETF嘉实</td><th>基金类型</th><td>指数型-股票</td></tr>
  <tr><th>成立日期/规模</th><td>2022年09月30日 / 3.669亿份</td>
      <th>净资产规模</th><td>642.79亿元</td></tr>
  <tr><th>基金管理人</th><td><a href="#">嘉实基金</a></td>
      <th>基金托管人</th><td><a href="#">中信证券</a></td></tr>
  <tr><th>管理费率</th><td>0.50%（每年）</td><th>托管费率</th><td>0.10%（每年）</td></tr>
  <tr><th>销售服务费率</th><td>---（每年）</td><th>最高认购费率</th><td>0.80%</td></tr>
  <tr><th>业绩比较基准</th><td style="width:300px">上证科创板芯片指数收益率</td>
      <th>跟踪标的</th><td>上证科创板芯片指数</td></tr>
</table>
</body></html>
"""


def test_profile_parses_disclosed_fields():
    profile = parse_fund_profile(PROFILE_HTML)

    assert profile["fund_name"] == "嘉实上证科创板芯片交易型开放式指数证券投资基金"
    assert profile["short_name"] == "科创芯片ETF嘉实"
    assert profile["fund_type"] == "指数型-股票"
    assert profile["established_date"] == date(2022, 9, 30)
    assert profile["manager_name"] == "嘉实基金"
    assert profile["custodian_name"] == "中信证券"
    assert profile["management_fee_pct"] == Decimal("0.50")
    assert profile["custodian_fee_pct"] == Decimal("0.10")
    assert profile["tracking_target"] == "上证科创板芯片指数"
    assert profile["benchmark"] == "上证科创板芯片指数收益率"


def test_placeholder_values_stay_null():
    """上游用 '---' 表示未披露，必须留 NULL 而不是当成 0。"""
    html = "<tr><th>管理费率</th><td>---（每年）</td></tr>"

    profile = parse_fund_profile(html)

    assert profile["management_fee_pct"] is None


def test_established_date_falls_back_to_the_table_value():
    html = "<tr><th>成立日期/规模</th><td>2015年05月06日 / 10亿份</td></tr>"

    profile = parse_fund_profile(html)

    assert profile["established_date"] == date(2015, 5, 6)


def test_profile_without_expected_fields_returns_nulls():
    profile = parse_fund_profile("<html><body>空的页面</body></html>")

    assert profile["established_date"] is None
    assert profile["manager_name"] is None
    assert profile["tracking_target"] is None
