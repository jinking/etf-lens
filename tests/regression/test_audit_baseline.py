"""`etf audit` 的规则清单基线。

冻结"当前有哪些规则、什么级别、干净库是否通过"。V2 新增规则（未来数据、
复权版本、同类分组…）时必须一起更新这份清单——规则被删或级别被改都会失败。
"""

from typer.testing import CliRunner

from etf_engine.audit import run_audit
from etf_engine.cli.app import app as cli_app

EXPECTED_RULES = {
    "architecture": "ERROR",
    "rows_on_non_trading_days": "ERROR",
    "orphan_mart_rows": "ERROR",
    "estimates_without_version": "ERROR",
    "mixed_calculation_versions": "WARN",
    "zero_substituted_for_unknown": "ERROR",
    "missing_source_metadata": "ERROR",
    "holdings_without_report_date": "ERROR",
    "incomplete_market_turnover": "WARN",
    "future_data_in_research_snapshot": "ERROR",
    "unadjusted_flow_crosses_corporate_action": "ERROR",
    "adjusted_series_missing_version": "ERROR",
    "adjusted_series_future_action_leak": "ERROR",
    "docs_consistency": "WARN",
}


def test_audit_rule_inventory_is_frozen(warehouse_db):
    result = run_audit(database_path=warehouse_db)

    assert {check["name"]: check["severity"] for check in result["checks"]} == EXPECTED_RULES


def test_clean_warehouse_passes_every_rule(warehouse_db):
    result = run_audit(database_path=warehouse_db)

    assert result["error_count"] == 0
    assert result["status"] == "PASS"
    assert all(check["count"] == 0 for check in result["checks"])


def test_audit_cli_strict_mode_returns_zero_on_clean_data(warehouse):
    result = CliRunner().invoke(cli_app, ["audit", "--strict", "--json"])

    assert result.exit_code == 0, result.stdout
    assert '"status": "PASS"' in result.stdout.replace("\n", " ")


def test_audit_cli_blocks_on_error(warehouse):
    """故意写入一条"不可能为 0 的字段等于 0"，严格模式必须非 0 退出。"""
    from etf_engine.config.settings import settings
    from etf_engine.db.connection import connect

    with connect(settings.database_path) as con:
        con.execute(
            """
            UPDATE core.etf_share_daily SET shares = 0
            WHERE security_id = '510300.SH'
            """
        )

    result = CliRunner().invoke(cli_app, ["audit", "--strict"])

    assert result.exit_code != 0
    assert "zero_substituted_for_unknown" in result.stdout
