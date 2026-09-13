from enum import StrEnum


class Exchange(StrEnum):
    SSE = "SSE"
    SZSE = "SZSE"
    BJSE = "BJSE"
    HKEX = "HKEX"


class AssetType(StrEnum):
    ETF = "ETF"


class QualityStatus(StrEnum):
    VERIFIED = "VERIFIED"
    PASS = "PASS"
    WARN = "WARN"
    CONFLICT = "CONFLICT"
    STALE = "STALE"
    FAILED = "FAILED"


class RunStatus(StrEnum):
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


class CorporateActionType(StrEnum):
    """公司行为类型（披露口径，不由价格跳变推断）。"""

    SPLIT = "SPLIT"
    REVERSE_SPLIT = "REVERSE_SPLIT"
    SHARE_CONVERSION = "SHARE_CONVERSION"
    DIVIDEND = "DIVIDEND"
    OTHER = "OTHER"


class BenchmarkReturnBasis(StrEnum):
    """基准收益口径。口径不明时不允许计算跟踪差异。"""

    PRICE_INDEX = "price_index"
    TOTAL_RETURN_INDEX = "total_return_index"
    NET_TOTAL_RETURN_INDEX = "net_total_return_index"
    UNKNOWN = "unknown"
