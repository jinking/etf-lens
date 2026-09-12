"""交易日历（纯领域对象，不做任何 I/O）。

``docs/TECHNICAL.md`` §8 要求同步必须基于真实交易日历，禁止用
Monday-Friday 简化判断。历史实现用 ``datetime.now().date()`` 直接当交易日，
结果把一条周六（2026-09-12）的深交所份额数据写了进库。
"""

from bisect import bisect_left, bisect_right
from dataclasses import dataclass, field
from datetime import date, datetime

#: 收盘后数据（份额/净值）通常的发布时点。早于该时点运行时，当日快照尚未
#: 发布，as-of 应回退到上一个交易日。
DEFAULT_DATA_READY_HOUR = 17


@dataclass(frozen=True, slots=True)
class MarketCalendar:
    """已排序的交易日集合。"""

    trading_days: tuple[date, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        days = tuple(sorted(set(self.trading_days)))
        if not days:
            raise ValueError("Trading calendar must contain at least one trading day.")
        object.__setattr__(self, "trading_days", days)

    @classmethod
    def from_iterable(cls, values) -> "MarketCalendar":
        return cls(tuple(values))

    @property
    def first_day(self) -> date:
        return self.trading_days[0]

    @property
    def last_day(self) -> date:
        return self.trading_days[-1]

    def covers(self, value: date) -> bool:
        """日历是否覆盖该日期。未覆盖时不应据此判定"非交易日"。"""
        return self.first_day <= value <= self.last_day

    def is_trading_day(self, value: date) -> bool:
        index = bisect_left(self.trading_days, value)
        return index < len(self.trading_days) and self.trading_days[index] == value

    def latest_trading_day(self, asof: date) -> date | None:
        """返回 <= asof 的最近交易日，早于日历起点时返回 None。"""
        index = bisect_right(self.trading_days, asof)
        return self.trading_days[index - 1] if index else None

    def previous_trading_day(self, value: date) -> date | None:
        """返回严格早于 value 的最近交易日。"""
        index = bisect_left(self.trading_days, value)
        return self.trading_days[index - 1] if index else None

    def trading_days_back(self, asof: date, limit: int) -> list[date]:
        """从 <= asof 的最近交易日开始，向前取 limit 个交易日（降序）。"""
        if limit <= 0:
            return []
        index = bisect_right(self.trading_days, asof)
        start = max(index - limit, 0)
        return list(reversed(self.trading_days[start:index]))

    def latest_closed_trading_day(
        self,
        now: datetime,
        *,
        data_ready_hour: int = DEFAULT_DATA_READY_HOUR,
    ) -> date:
        """返回最近一个"数据已应发布"的交易日。

        规则：

        - 今天不是交易日：回退到上一个交易日；
        - 今天是交易日但早于 data_ready_hour：当日数据尚未发布，回退一个交易日；
        - 其余情况返回今天。
        """
        today = now.date()
        candidate = self.latest_trading_day(today)
        if candidate is None:
            raise ValueError(f"No trading day on or before {today} in calendar.")
        if candidate == today and now.hour < data_ready_hour:
            previous = self.previous_trading_day(candidate)
            if previous is None:
                raise ValueError(f"No trading day before {candidate} in calendar.")
            return previous
        return candidate
