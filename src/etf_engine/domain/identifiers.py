"""Canonical security identifiers.

内部统一使用 ``ticker.suffix`` 形式的主键：

```text
588200.SH   上交所
159915.SZ   深交所
920002.BJ   北交所
01801.HK    港交所
```

推断规则刻意保守：只有在代码形态唯一对应一个市场时才允许省略后缀，
其余情况一律报错。宁可让调用方显式指明市场，也不要猜出一个看起来合理
但实际错误的主键——历史上 ``SecurityId.parse`` 曾把 5 位港股代码补零成
6 位后推断为深市，导致 ``01801``（信达生物）被写成 ``001801.SZ``，并与
真实存在但完全无关的深市 A 股代码发生静默合并。
"""

from dataclasses import dataclass

from .enums import Exchange

SUFFIX_TO_EXCHANGE: dict[str, Exchange] = {
    "SH": Exchange.SSE,
    "SZ": Exchange.SZSE,
    "BJ": Exchange.BJSE,
    "HK": Exchange.HKEX,
}

EXCHANGE_TO_SUFFIX: dict[Exchange, str] = {value: key for key, value in SUFFIX_TO_EXCHANGE.items()}

#: A 股代码的证券位数。
ASHARE_CODE_LENGTH = 6

#: 港股代码的标准位数（上游接口统一返回 5 位，如 ``01801``）。
HKEX_CODE_LENGTH = 5

#: 6 位 A 股代码前缀到交易所的静态映射。
#:
#: 先匹配两位前缀（``92`` / ``90``）再匹配一位前缀，避免 ``920xxx`` 与
#: ``900xxx`` 互相污染。
ASHARE_PREFIX_RULES: tuple[tuple[tuple[str, ...], Exchange], ...] = (
    (("92",), Exchange.BJSE),  # 北交所 920xxx
    (("90",), Exchange.SSE),  # 沪市 B 股 900xxx
    (("4", "8"), Exchange.BJSE),  # 北交所 430xxx / 83xxxx / 87xxxx / 88xxxx
    (("2",), Exchange.SZSE),  # 深市 B 股 200xxx
    (("5", "6"), Exchange.SSE),
    (("0", "1", "3"), Exchange.SZSE),
)


@dataclass(frozen=True, slots=True)
class SecurityId:
    ticker: str
    exchange: Exchange

    @property
    def value(self) -> str:
        return f"{self.ticker}.{EXCHANGE_TO_SUFFIX[self.exchange]}"

    @classmethod
    def parse(cls, value: str) -> "SecurityId":
        raw = str(value).strip().upper()
        if not raw:
            raise ValueError("Security id must not be empty.")

        if "." in raw:
            ticker, suffix = raw.split(".", 1)
            exchange = SUFFIX_TO_EXCHANGE.get(suffix)
            if exchange is None:
                raise ValueError(f"Unsupported exchange suffix: {suffix}")
            return cls(ticker=_normalize_ticker(ticker, exchange), exchange=exchange)

        if not raw.isdigit():
            raise ValueError(f"Security id must be numeric or carry an exchange suffix: {raw}")

        if len(raw) == HKEX_CODE_LENGTH:
            return cls(ticker=raw, exchange=Exchange.HKEX)

        if len(raw) == ASHARE_CODE_LENGTH:
            for prefixes, exchange in ASHARE_PREFIX_RULES:
                if raw.startswith(prefixes):
                    return cls(ticker=raw, exchange=exchange)

        raise ValueError(
            "Cannot infer exchange safely. Pass canonical id such as "
            "588200.SH, 159915.SZ, 920002.BJ or 01801.HK."
        )


def _normalize_ticker(ticker: str, exchange: Exchange) -> str:
    if not ticker.isdigit():
        raise ValueError(f"Ticker must be numeric: {ticker}")
    width = HKEX_CODE_LENGTH if exchange is Exchange.HKEX else ASHARE_CODE_LENGTH
    if len(ticker) > width:
        raise ValueError(f"Ticker {ticker} is longer than {width} digits for {exchange.value}")
    return ticker.zfill(width)
