"""净申购累积曲线的口径测试。

关键纪律：缺失日**既不补 0 也不插值**。补 0 会把"那天不知道"画成
"那天没有资金进出"，在累积曲线上两者是完全不同的结论。
"""

from etf_engine.research.flow import cumulative_series


def _points(values):
    return [
        {"trade_date": f"2026-09-{index + 1:02d}", "daily_net_subscription": value}
        for index, value in enumerate(values)
    ]


def test_cumulative_sums_in_order():
    result = cumulative_series(_points([1e8, 2e8, -5e7]))

    assert [point["cumulative_net_subscription"] for point in result] == [1e8, 3e8, 2.5e8]
    assert result[-1]["daily_net_subscription"] == -5e7


def test_missing_day_is_not_treated_as_zero():
    result = cumulative_series(_points([1e8, None, 2e8]))

    # 缺失那天：当日为 NULL、累积也为 NULL，而不是把 0 累加进去
    assert result[1]["daily_net_subscription"] is None
    assert result[1]["cumulative_net_subscription"] is None
    # 下一天继续从上一个已知值累加
    assert result[2]["cumulative_net_subscription"] == 3e8


def test_cumulative_keeps_extra_fields():
    points = [
        {"trade_date": "2026-09-01", "daily_net_subscription": 1e8, "contributor_count": 3},
    ]
    result = cumulative_series(points)

    assert result[0]["contributor_count"] == 3
