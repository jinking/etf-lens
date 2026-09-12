"""数据质量问题的统一表达。

对应 ``ops.quality_issue`` 表。Adapter 解析、Validator 校验、Reconciler
对账都产出这一种结构，避免出现多份形状相同的"问题对象"。
"""

from dataclasses import dataclass

from .enums import QualityStatus

SEVERITY_ERROR = "ERROR"
SEVERITY_WARN = "WARN"


@dataclass(frozen=True, slots=True)
class DataQualityIssue:
    severity: str
    rule_name: str
    details: str

    @property
    def is_blocking(self) -> bool:
        return self.severity == SEVERITY_ERROR


def warn(rule_name: str, details: str) -> DataQualityIssue:
    return DataQualityIssue(severity=SEVERITY_WARN, rule_name=rule_name, details=details)


def error(rule_name: str, details: str) -> DataQualityIssue:
    return DataQualityIssue(severity=SEVERITY_ERROR, rule_name=rule_name, details=details)


__all__ = [
    "SEVERITY_ERROR",
    "SEVERITY_WARN",
    "DataQualityIssue",
    "QualityStatus",
    "error",
    "warn",
]
