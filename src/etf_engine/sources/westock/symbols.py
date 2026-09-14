from etf_engine.domain.enums import Exchange
from etf_engine.domain.identifiers import SecurityId


def to_westock_symbol(security_id: str) -> str:
    """将系统内部 SecurityId（如 '510300.SH', '159915.SZ'）转换为 WeStock 格式（'sh510300', 'sz159915'）。"""
    sid = SecurityId.parse(security_id)
    if sid.exchange == Exchange.SSE:
        return f"sh{sid.ticker}"
    if sid.exchange == Exchange.SZSE:
        return f"sz{sid.ticker}"
    if sid.exchange == Exchange.BSE:
        return f"bj{sid.ticker}"
    raise ValueError(f"WeStock 不支持该交易所证券代码: {security_id}")


def to_security_id(westock_code: str) -> str:
    """将 WeStock 格式（'sh510300', 'sz159915'）转换为系统内部 SecurityId（'510300.SH', '159915.SZ'）。"""
    code = westock_code.strip()
    lower = code.lower()
    if lower.startswith("sh"):
        return f"{code[2:]}.SH"
    if lower.startswith("sz"):
        return f"{code[2:]}.SZ"
    if lower.startswith("bj"):
        return f"{code[2:]}.BJ"
    if lower.startswith("hk"):
        return f"{code[2:]}.HK"
    raise ValueError(f"无法解析 WeStock 证券代码: {westock_code}")
