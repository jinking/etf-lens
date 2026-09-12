from abc import ABC, abstractmethod
from datetime import date

from etf_engine.domain.models import (
    ETFHolding,
    ETFMaster,
    ETFNav,
    ETFQuote,
    ETFShare,
    IndexConstituent,
)
from etf_engine.domain.quality import DataQualityIssue


class ETFQuoteSource(ABC):
    @abstractmethod
    def fetch_quotes(self, trade_date: date | None = None) -> list[ETFQuote]:
        raise NotImplementedError


class ETFHistorySource(ABC):
    @abstractmethod
    def fetch_history(
        self,
        security_id: str,
        start_date: date,
        end_date: date,
    ) -> list[ETFQuote]:
        raise NotImplementedError


class ETFShareSource(ABC):
    #: True 表示该来源不携带统计日期，入库日期由交易日历推导（需要在库中标注）。
    snapshot_date_is_derived: bool = False
    #: 数据源短名，用于 ops.ingestion_run 与 raw 快照目录。
    source_name: str = "unknown"
    #: True 表示该来源可以按历史交易日逐日回补（仅当数据自带统计日期时才允许）。
    supports_history_backfill: bool = False

    @abstractmethod
    def fetch_shares(self, trade_date: date | None = None) -> list[ETFShare]:
        raise NotImplementedError

    def fetch_shares_with_issues(
        self, trade_date: date | None = None
    ) -> tuple[list[ETFShare], list[DataQualityIssue]]:
        """返回份额事实与被跳过的行所对应的问题。"""
        return self.fetch_shares(trade_date=trade_date), []

    def fetch_shares_history(
        self, asof: date, trading_days: int
    ) -> tuple[list[ETFShare], list[DataQualityIssue]]:
        """回补最近 ``trading_days`` 个交易日的份额。

        只有自带统计日期的来源允许实现：对快照类来源（如深交所当前份额），
        逐日回补等于把同一条快照复制到多个日期上，属于伪造历史。
        """
        raise NotImplementedError(
            f"{type(self).__name__} 不支持份额历史回补（快照没有自带统计日期）"
        )


class ETFMasterSource(ABC):
    @abstractmethod
    def fetch_masters(self) -> list[ETFMaster]:
        raise NotImplementedError

    def fetch_masters_with_issues(
        self,
    ) -> tuple[list[ETFMaster], list[DataQualityIssue]]:
        return self.fetch_masters(), []


class ETFNavSource(ABC):
    @abstractmethod
    def fetch_navs(self, trade_date: date | None = None) -> list[ETFNav]:
        raise NotImplementedError

    def fetch_navs_with_issues(
        self, trade_date: date | None = None
    ) -> tuple[list[ETFNav], list[DataQualityIssue]]:
        return self.fetch_navs(trade_date=trade_date), []


class ETFHoldingSource(ABC):
    @abstractmethod
    def fetch_holdings(self, security_id: str, report_date: date | None = None) -> list[ETFHolding]:
        raise NotImplementedError

    def fetch_holdings_with_issues(
        self, security_id: str, report_date: date | None = None
    ) -> tuple[list[ETFHolding], list[DataQualityIssue]]:
        return self.fetch_holdings(security_id, report_date=report_date), []


class IndexConstituentSource(ABC):
    @abstractmethod
    def fetch_constituents(
        self, index_id: str, effective_date: date | None = None
    ) -> list[IndexConstituent]:
        raise NotImplementedError


class TradingCalendarSource(ABC):
    """交易日历能力接口。

    同步任务不允许自行用 Monday-Friday 推断交易日，必须通过该能力拿到
    权威交易日集合。
    """

    @abstractmethod
    def fetch_trading_days(self, start_date: date, end_date: date) -> list[date]:
        raise NotImplementedError
