"""自检：把 ``AGENTS.md`` 的不可破坏约束变成可执行检查。

两条主线：

* :mod:`etf_engine.audit.architecture`：静态检查依赖方向（离线的 AST 扫描）；
* :mod:`etf_engine.audit.data_rules`：数据库不变量（缺失不许当 0、日期必须是交易日、
  估算必须带口径等）。

设计原则：每条规则都要**能被触发**——测试里必须先造出违规数据、确认它被抓到，
否则规则只是装饰。
"""

from etf_engine.audit.architecture import ARCHITECTURE_RULES, check_architecture
from etf_engine.audit.data_rules import DATA_RULES, run_data_rules
from etf_engine.audit.runner import SEVERITY_ERROR, SEVERITY_WARN, run_audit

__all__ = [
    "ARCHITECTURE_RULES",
    "DATA_RULES",
    "SEVERITY_ERROR",
    "SEVERITY_WARN",
    "check_architecture",
    "run_audit",
    "run_data_rules",
]
