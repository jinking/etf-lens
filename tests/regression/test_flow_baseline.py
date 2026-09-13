"""`etf compute-mart` 的数值基线（研究指标 + 资金流）。"""

import pytest

from etf_engine.config.settings import settings
from etf_engine.db.connection import connect


def _row(table: str, security_id: str) -> dict:
    with connect(settings.database_path) as con:
        row = con.execute(f"SELECT * FROM {table} WHERE security_id = ?", [security_id]).fetchone()
        columns = [item[0] for item in con.description]
    assert row is not None, f"{table} 缺少 {security_id}"
    return dict(zip(columns, row, strict=True))


def test_metric_row_is_frozen(warehouse):
    row = _row("mart.etf_metric_daily", "510300.SH")

    assert row["calculation_version"] == "metric_v1"
    assert row["trade_date"].isoformat() == warehouse
    assert row["return_1d"] == pytest.approx(1 / 123)
    assert row["return_20d"] == pytest.approx(124 / 104 - 1)
    assert row["return_60d"] is None, "只有 25 个交易日，60 日窗口不足"
    assert row["max_drawdown_60d"] is None, "窗口不足时返回 NULL，不用近似值"
    assert row["current_drawdown"] == 0.0
    assert row["avg_turnover_amount_20d"] == pytest.approx(1_014_500)
    # 25 个交易日刚好够 20 日窗口：单调序列的波动率很小但不为 0
    assert row["volatility_20d"] == pytest.approx(0.00712169492437755)
    assert row["volatility_60d"] is None


def test_flow_row_is_frozen(warehouse):
    row = _row("mart.etf_flow_daily", "510300.SH")

    assert row["calculation_version"] == "flow_v1"
    assert row["is_estimated"] is True
    assert row["share_change_1d"] == 10.0
    assert row["share_change_5d"] == 50.0
    assert row["share_change_20d"] == 200.0
    assert row["share_change_pct_20d"] == pytest.approx(200 / 1040)
    assert row["estimated_net_subscription_1d"] == pytest.approx(15.0)
    assert row["estimated_net_subscription_20d"] == pytest.approx(300.0)
    assert row["consecutive_share_inflow_days"] == 24
    assert row["consecutive_share_outflow_days"] == 0


def test_flow_uses_nav_from_the_nav_table_when_share_row_has_none(warehouse):
    """份额行没有净值时，用 core.etf_nav_daily 按同一天补齐（不是插值、不是就近取）。"""
    with connect(settings.database_path) as con:
        con.execute("UPDATE core.etf_share_daily SET nav = NULL WHERE security_id = '510300.SH'")

    from etf_engine.jobs.compute_mart import compute_mart

    compute_mart(security_ids=["510300.SH"])

    row = _row("mart.etf_flow_daily", "510300.SH")
    assert row["estimated_net_subscription_20d"] == pytest.approx(300.0)


def test_mart_only_covers_etfs_with_facts(warehouse):
    with connect(settings.database_path) as con:
        ids = [
            row[0]
            for row in con.execute(
                "SELECT DISTINCT security_id FROM mart.etf_metric_daily ORDER BY 1"
            ).fetchall()
        ]

    assert ids == ["159919.SZ", "510300.SH", "588200.SH"]
