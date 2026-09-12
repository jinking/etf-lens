from dataclasses import dataclass

from .enums import Exchange


@dataclass(frozen=True, slots=True)
class SecurityId:
    ticker: str
    exchange: Exchange

    @property
    def value(self) -> str:
        suffix = "SH" if self.exchange == Exchange.SSE else "SZ"
        return f"{self.ticker}.{suffix}"

    @classmethod
    def parse(cls, value: str) -> "SecurityId":
        value = value.strip().upper()
        if "." in value:
            ticker, suffix = value.split(".", 1)
            if suffix == "SH":
                return cls(ticker=ticker, exchange=Exchange.SSE)
            if suffix == "SZ":
                return cls(ticker=ticker, exchange=Exchange.SZSE)
            raise ValueError(f"Unsupported exchange suffix: {suffix}")

        if value.startswith(("5", "6")):
            return cls(ticker=value, exchange=Exchange.SSE)
        if value.startswith(("0", "1", "3")):
            return cls(ticker=value, exchange=Exchange.SZSE)
        raise ValueError(
            "Cannot infer exchange safely. Pass canonical id such as 588200.SH or 159915.SZ."
        )

