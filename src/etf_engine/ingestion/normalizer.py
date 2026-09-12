"""Normalizer 边界。

具体第三方字段到 Domain Model 的转换优先放在各 Adapter 内。
本模块用于跨数据源都需要的通用标准化规则，例如：

- security_id canonicalization
- percentage unit normalization
- date normalization
- currency / share unit normalization

禁止在这里加入投资研究指标。
"""

from etf_engine.domain.identifiers import SecurityId


def normalize_security_id(value: str) -> str:
    return SecurityId.parse(value).value


def normalize_premium_discount(close: float | None, iopv: float | None) -> float | None:
    """Return the canonical premium convention: positive means premium."""
    if close is None or iopv is None or iopv <= 0:
        return None
    return (close - iopv) / iopv
