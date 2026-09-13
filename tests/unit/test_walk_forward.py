"""旧模块名 ``walk_forward`` 只做兼容转发，实现已迁到 ``regime_validation``。

这组测试的价值是防止"兼容层悄悄长出第二套实现"：所有符号都必须是同一个对象。
"""

from etf_engine.research import regime_validation, walk_forward


def test_walk_forward_reexports_the_same_objects():
    assert walk_forward.build_report is regime_validation.build_report
    assert walk_forward.forward_outcomes is regime_validation.forward_outcomes
    assert walk_forward.render_markdown is regime_validation.render_markdown
    assert walk_forward.state_summary is regime_validation.state_summary


def test_walk_forward_report_alias_points_at_regime_report():
    assert walk_forward.WalkForwardReport is regime_validation.RegimeValidationReport
    assert walk_forward.ForwardOutcome is regime_validation.ForwardOutcome
