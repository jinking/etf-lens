"""兼容层：历史验证的实现已迁移到 :mod:`etf_engine.research.regime_validation`。

升级方案 §16 要求：这项能力更准确的叫法是 **Historical Regime Validation**，
因此实现与文档统一到 ``regime_validation``；本模块只做旧导入路径的转发，
不再承载任何逻辑，避免同一套统计出现两份实现。

新代码请直接 ``from etf_engine.research.regime_validation import ...``。
"""

from etf_engine.research.regime_validation import (
    FORWARD_WINDOWS,
    REGIME_DEFINITION,
    SAMPLE_DAILY,
    SAMPLE_TRANSITION,
    ForwardOutcome,
    ForwardStats,
    RegimeSlice,
    RegimeValidationReport,
    StateSummary,
    build_regime_slices,
    build_report,
    forward_outcomes,
    render_markdown,
    state_durations,
    state_entries,
    state_summary,
    switch_count,
)

#: 旧名字保留：V2 里的模块叫 walk-forward，实际语义是 regime validation。
WalkForwardReport = RegimeValidationReport

__all__ = [
    "FORWARD_WINDOWS",
    "REGIME_DEFINITION",
    "SAMPLE_DAILY",
    "SAMPLE_TRANSITION",
    "ForwardOutcome",
    "ForwardStats",
    "RegimeSlice",
    "RegimeValidationReport",
    "StateSummary",
    "WalkForwardReport",
    "build_regime_slices",
    "build_report",
    "forward_outcomes",
    "render_markdown",
    "state_durations",
    "state_entries",
    "state_summary",
    "switch_count",
]
