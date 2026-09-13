"""数据自检规则必须"能被触发"。

每条规则都构造一份**故意违规**的最小数据，确认它被抓到；再用干净数据确认不误报。
只测"干净库返回 0 条"是不够的——规则可能早就失效了（比如表名改了）。
"""

from datetime import date, datetime, timedelta

from etf_engine.audit.data_rules import run_data_rules
from etf_engine.config.settings import settings
from etf_engine.db.connection import connect
from etf_engine.db.migrate import run_migrations
from etf_engine.repositories.trading_calendar_repository import TradingCalendarRepository

FETCHED_AT = datetime(2026, 9, 12, 18, 0)
TRADING_DAY = date(2026, 9, 10)  # 周四
FUTURE_DAY = date(2026, 9, 11)  # 周五，行情事实还没有这一天
SATURDAY = date(2026, 9, 12)


def _prepare(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(settings, "database_path", tmp_path / "etf.duckdb")
    run_migrations()
    base = date(2026, 1, 1)
    TradingCalendarRepository().upsert_many(
        [
            base + timedelta(days=offset)
            for offset in range(365)
            if (base + timedelta(days=offset)).weekday() < 5
        ],
        source="test",
        upstream_source="test",
    )


def _results() -> dict[str, dict]:
    return {item["name"]: item for item in run_data_rules()}


def test_clean_database_passes_every_rule(tmp_path, monkeypatch):
    _prepare(tmp_path, monkeypatch)

    for name, check in _results().items():
        assert check["count"] == 0, f"{name} 在空库上误报：{check['violations']}"


def test_non_trading_day_rows_are_caught(tmp_path, monkeypatch):
    _prepare(tmp_path, monkeypatch)
    with connect(settings.database_path) as con:
        con.execute(
            """
            INSERT INTO core.etf_quote_daily
                (security_id, trade_date, close, source, fetched_at, quality_status)
            VALUES ('588200.SH', ?, 1.0, 'test', ?, 'PASS')
            """,
            [SATURDAY, FETCHED_AT],
        )

    check = _results()["rows_on_non_trading_days"]

    assert check["count"] == 1
    assert "2026-09-12" in check["violations"][0]["detail"]


def test_estimates_without_version_are_caught(tmp_path, monkeypatch):
    _prepare(tmp_path, monkeypatch)
    with connect(settings.database_path) as con:
        con.execute(
            """
            INSERT INTO mart.etf_flow_daily
                (security_id, trade_date, share_change_1d, is_estimated,
                 calculation_version, calculated_at)
            VALUES ('588200.SH', ?, 100, FALSE, 'flow_v1', ?)
            """,
            [TRADING_DAY, FETCHED_AT],
        )

    check = _results()["estimates_without_version"]

    assert check["count"] == 1
    assert "588200.SH" in check["violations"][0]["detail"]


def test_orphan_mart_rows_are_caught(tmp_path, monkeypatch):
    _prepare(tmp_path, monkeypatch)
    with connect(settings.database_path) as con:
        con.execute(
            """
            INSERT INTO mart.etf_flow_daily
                (security_id, trade_date, share_change_1d, is_estimated,
                 calculation_version, calculated_at)
            VALUES ('588200.SH', ?, 100, TRUE, 'flow_v1', ?)
            """,
            [TRADING_DAY, FETCHED_AT],
        )

    check = _results()["orphan_mart_rows"]

    assert check["count"] == 1
    assert "没有对应的份额事实" in check["violations"][0]["detail"]


def test_zero_share_is_caught(tmp_path, monkeypatch):
    _prepare(tmp_path, monkeypatch)
    with connect(settings.database_path) as con:
        con.execute(
            """
            INSERT INTO core.etf_share_daily
                (security_id, trade_date, shares, source, fetched_at, quality_status)
            VALUES ('560650.SH', ?, 0, 'sse', ?, 'PASS')
            """,
            [TRADING_DAY, FETCHED_AT],
        )

    check = _results()["zero_substituted_for_unknown"]

    assert check["count"] == 1
    assert "shares" in check["violations"][0]["detail"]


def test_missing_source_metadata_is_caught(tmp_path, monkeypatch):
    _prepare(tmp_path, monkeypatch)
    with connect(settings.database_path) as con:
        # source 是 NOT NULL，所以可触发的形态是空字符串（不是 NULL）
        con.execute(
            """
            INSERT INTO core.etf_quote_daily
                (security_id, trade_date, close, source, fetched_at, quality_status)
            VALUES ('588200.SH', ?, 1.0, '', ?, 'PASS')
            """,
            [TRADING_DAY, FETCHED_AT],
        )

    check = _results()["missing_source_metadata"]

    assert check["count"] == 1
    assert check["violations"][0]["dataset"] == "core.etf_quote_daily"


def test_holdings_report_date_guard_detects_schema_drift(tmp_path, monkeypatch):
    """持仓报告期由 NOT NULL / 主键兜底，规则改为 schema 守卫：约束没了必须报警。

    注意：DuckDB 对**主键列**执行 ``DROP NOT NULL`` 不会报错但也不会生效
    （实测），所以这里用"重建表且不带约束"的方式模拟 schema 漂移。
    """
    _prepare(tmp_path, monkeypatch)
    with connect(settings.database_path) as con:
        con.execute("DROP TABLE core.etf_holding_disclosure")
        con.execute(
            """
            CREATE TABLE core.etf_holding_disclosure (
                etf_id VARCHAR,
                report_date DATE,
                stock_id VARCHAR
            )
            """
        )

    check = _results()["holdings_without_report_date"]

    assert check["count"] == 1
    assert "NOT NULL" in check["violations"][0]["detail"]


def test_registered_versions_may_coexist(tmp_path, monkeypatch):
    """v1 与 v2 并存是 V2 的设计（历史口径保留 + 新口径并行），不算违规。"""
    _prepare(tmp_path, monkeypatch)
    with connect(settings.database_path) as con:
        con.executemany(
            """
            INSERT INTO mart.etf_metric_daily
                (security_id, trade_date, return_1d, calculation_version, calculated_at)
            VALUES (?, ?, 0.1, ?, ?)
            """,
            [
                ("588200.SH", TRADING_DAY, "metric_v1", FETCHED_AT),
                ("510300.SH", TRADING_DAY, "metric_v2", FETCHED_AT),
            ],
        )

    check = _results()["mixed_calculation_versions"]

    assert check["count"] == 0


def test_unregistered_calculation_version_is_caught(tmp_path, monkeypatch):
    _prepare(tmp_path, monkeypatch)
    with connect(settings.database_path) as con:
        con.execute(
            """
            INSERT INTO mart.etf_metric_daily
                (security_id, trade_date, return_1d, calculation_version, calculated_at)
            VALUES ('588200.SH', ?, 0.1, 'metric_v9', ?)
            """,
            [TRADING_DAY, FETCHED_AT],
        )

    check = _results()["mixed_calculation_versions"]

    assert check["count"] == 1
    assert "metric_v9" in check["violations"][0]["detail"]
    assert check["severity"] == "WARN"


def test_single_exchange_turnover_is_warned(tmp_path, monkeypatch):
    _prepare(tmp_path, monkeypatch)
    with connect(settings.database_path) as con:
        con.execute(
            """
            INSERT INTO core.market_turnover_daily
                (trade_date, exchange, turnover_amount, source, fetched_at, quality_status)
            VALUES (?, 'SSE', 1.0e12, 'sse', ?, 'PASS')
            """,
            [TRADING_DAY, FETCHED_AT],
        )

    check = _results()["incomplete_market_turnover"]

    assert check["count"] == 1
    assert check["severity"] == "WARN"


def test_mart_rows_ahead_of_facts_are_flagged(tmp_path, monkeypatch):
    """派生行领先于事实 = 用到了当时还不存在的数据（Point-in-Time 违规）。"""
    _prepare(tmp_path, monkeypatch)
    with connect(settings.database_path) as con:
        con.execute(
            """
            INSERT INTO core.etf_quote_daily
                (security_id, trade_date, close, source, fetched_at, quality_status)
            VALUES ('588200.SH', ?, 1.0, 'test', ?, 'PASS')
            """,
            [TRADING_DAY, FETCHED_AT],
        )
        con.execute(
            """
            INSERT INTO mart.etf_metric_daily
                (security_id, trade_date, return_1d, calculation_version, calculated_at)
            VALUES ('588200.SH', ?, 0.1, 'metric_v1', ?)
            """,
            [FUTURE_DAY, FETCHED_AT],
        )

    check = _results()["future_data_in_research_snapshot"]

    assert check["count"] == 1
    assert "core.etf_quote_daily 只到" in check["violations"][0]["detail"]


def test_mart_rows_within_fact_range_are_clean(tmp_path, monkeypatch):
    _prepare(tmp_path, monkeypatch)
    with connect(settings.database_path) as con:
        con.execute(
            """
            INSERT INTO core.etf_quote_daily
                (security_id, trade_date, close, source, fetched_at, quality_status)
            VALUES ('588200.SH', ?, 1.0, 'test', ?, 'PASS')
            """,
            [TRADING_DAY, FETCHED_AT],
        )
        con.execute(
            """
            INSERT INTO mart.etf_metric_daily
                (security_id, trade_date, return_1d, calculation_version, calculated_at)
            VALUES ('588200.SH', ?, 0.1, 'metric_v1', ?)
            """,
            [TRADING_DAY, FETCHED_AT],
        )

    assert _results()["future_data_in_research_snapshot"]["count"] == 0


def test_adjusted_row_without_version_is_flagged(tmp_path, monkeypatch):
    _prepare(tmp_path, monkeypatch)
    with connect(settings.database_path) as con:
        con.execute(
            """
            INSERT INTO mart.etf_adjusted_daily
                (security_id, trade_date, adjustment_factor, calculation_version, calculated_at)
            VALUES ('588200.SH', ?, 2.0, '', ?)
            """,
            [TRADING_DAY, FETCHED_AT],
        )

    check = _results()["adjusted_series_missing_version"]

    assert check["count"] >= 1
    assert "缺少 calculation_version" in check["violations"][0]["detail"]


def test_adjusted_factor_using_a_future_action_is_flagged(tmp_path, monkeypatch):
    """历史行用了未来才知道的折算 → Point-in-Time 泄漏。"""
    _prepare(tmp_path, monkeypatch)
    with connect(settings.database_path) as con:
        con.execute(
            """
            INSERT INTO core.etf_corporate_action
                (security_id, action_date, action_type, share_adjustment_factor,
                 source, fetched_at, quality_status)
            VALUES ('588200.SH', ?, 'SPLIT', 2.0, 'test', ?, 'PASS')
            """,
            [FUTURE_DAY, FETCHED_AT],
        )
        # 折算发生在 FUTURE_DAY，但 TRADING_DAY 那一行已经用了因子 2
        con.execute(
            """
            INSERT INTO mart.etf_adjusted_daily
                (security_id, trade_date, adjustment_factor, calculation_version, calculated_at)
            VALUES ('588200.SH', ?, 2.0, 'adjust_v1', ?)
            """,
            [TRADING_DAY, FETCHED_AT],
        )

    check = _results()["adjusted_series_future_action_leak"]

    assert check["count"] == 1
    assert "按当日可知行为推算的 1.0" in check["violations"][0]["detail"]


def test_flow_v1_crossing_a_split_is_flagged(tmp_path, monkeypatch):
    _prepare(tmp_path, monkeypatch)
    with connect(settings.database_path) as con:
        con.execute(
            """
            INSERT INTO core.etf_corporate_action
                (security_id, action_date, action_type, share_adjustment_factor,
                 source, fetched_at, quality_status)
            VALUES ('588200.SH', ?, 'SPLIT', 2.0, 'test', ?, 'PASS')
            """,
            [TRADING_DAY, FETCHED_AT],
        )
        con.execute(
            """
            INSERT INTO mart.etf_flow_daily
                (security_id, trade_date, share_change_1d, is_estimated,
                 calculation_version, calculated_at)
            VALUES ('588200.SH', ?, 1000.0, TRUE, 'flow_v1', ?)
            """,
            [TRADING_DAY, FETCHED_AT],
        )

    check = _results()["unadjusted_flow_crosses_corporate_action"]

    assert check["count"] == 1
    assert "机械份额变化会被误读成申赎" in check["violations"][0]["detail"]


def test_flow_v2_crossing_a_split_is_accepted(tmp_path, monkeypatch):
    _prepare(tmp_path, monkeypatch)
    with connect(settings.database_path) as con:
        con.execute(
            """
            INSERT INTO core.etf_corporate_action
                (security_id, action_date, action_type, share_adjustment_factor,
                 source, fetched_at, quality_status)
            VALUES ('588200.SH', ?, 'SPLIT', 2.0, 'test', ?, 'PASS')
            """,
            [TRADING_DAY, FETCHED_AT],
        )
        con.execute(
            """
            INSERT INTO mart.etf_flow_daily
                (security_id, trade_date, share_change_1d, is_estimated,
                 calculation_version, flow_quality_status, calculated_at)
            VALUES ('588200.SH', ?, 0.0, TRUE, 'flow_v2', 'corporate_action_adjusted', ?)
            """,
            [TRADING_DAY, FETCHED_AT],
        )

    assert _results()["unadjusted_flow_crosses_corporate_action"]["count"] == 0


def test_flow_v1_across_a_split_is_only_flagged_without_a_v2_row(tmp_path, monkeypatch):
    """v1 是保留的历史口径；只有"缺 v2 可读口径"时才算违规。"""
    _prepare(tmp_path, monkeypatch)
    with connect(settings.database_path) as con:
        con.execute(
            """
            INSERT INTO core.etf_corporate_action
                (security_id, action_date, action_type, share_adjustment_factor,
                 source, fetched_at, quality_status)
            VALUES ('588200.SH', ?, 'SPLIT', 2.0, 'test', ?, 'PASS')
            """,
            [TRADING_DAY, FETCHED_AT],
        )
        con.executemany(
            """
            INSERT INTO mart.etf_flow_daily
                (security_id, trade_date, share_change_1d, is_estimated,
                 calculation_version, calculated_at)
            VALUES ('588200.SH', ?, ?, TRUE, ?, ?)
            """,
            [
                (TRADING_DAY, 1000.0, "flow_v1", FETCHED_AT),
                (TRADING_DAY, 0.0, "flow_v2", FETCHED_AT),
            ],
        )

    assert _results()["unadjusted_flow_crosses_corporate_action"]["count"] == 0


def test_docs_consistency_is_clean_on_the_real_repo(tmp_path, monkeypatch):
    """文档漂移检查是结构化核对：命令存在、版本已登记、迁移表已写进数据模型。"""
    _prepare(tmp_path, monkeypatch)

    check = _results()["docs_consistency"]

    assert check["count"] == 0, check["violations"]


def test_cash_dividend_that_moves_share_factor_is_flagged(tmp_path, monkeypatch):
    """分红日份额因子跳变 → 会被读成假赎回，必须报出来。"""
    _prepare(tmp_path, monkeypatch)
    previous_day = TRADING_DAY - timedelta(days=1)
    with connect(settings.database_path) as con:
        con.execute(
            """
            INSERT INTO core.etf_corporate_action
                (security_id, action_date, action_type, cash_distribution,
                 source, fetched_at, quality_status)
            VALUES ('588200.SH', ?, 'DIVIDEND', 0.1, 'test', ?, 'PASS')
            """,
            [TRADING_DAY, FETCHED_AT],
        )
        con.executemany(
            """
            INSERT INTO mart.etf_adjusted_daily
                (security_id, trade_date, adjustment_factor, share_adjustment_factor,
                 calculation_version, calculated_at)
            VALUES ('588200.SH', ?, 1.0, ?, 'adjust_v1', ?)
            """,
            [(previous_day, 1.0, FETCHED_AT), (TRADING_DAY, 1.1, FETCHED_AT)],
        )

    check = _results()["cash_dividend_changes_share_factor"]

    assert check["count"] == 1
    assert "分红不改变份额" in check["violations"][0]["detail"]


def test_cash_dividend_with_stable_share_factor_is_clean(tmp_path, monkeypatch):
    _prepare(tmp_path, monkeypatch)
    previous_day = TRADING_DAY - timedelta(days=1)
    with connect(settings.database_path) as con:
        con.execute(
            """
            INSERT INTO core.etf_corporate_action
                (security_id, action_date, action_type, cash_distribution,
                 source, fetched_at, quality_status)
            VALUES ('588200.SH', ?, 'DIVIDEND', 0.1, 'test', ?, 'PASS')
            """,
            [TRADING_DAY, FETCHED_AT],
        )
        con.executemany(
            """
            INSERT INTO mart.etf_adjusted_daily
                (security_id, trade_date, adjustment_factor, share_adjustment_factor,
                 calculation_version, calculated_at)
            VALUES ('588200.SH', ?, ?, 1.0, 'adjust_v1', ?)
            """,
            [(previous_day, 1.0, FETCHED_AT), (TRADING_DAY, 1.0256, FETCHED_AT)],
        )

    assert _results()["cash_dividend_changes_share_factor"]["count"] == 0
