from enum import StrEnum


class Exchange(StrEnum):
    SSE = "SSE"
    SZSE = "SZSE"


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
