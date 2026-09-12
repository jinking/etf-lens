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
    @abstractmethod
    def fetch_shares(self, trade_date: date | None = None) -> list[ETFShare]:
        raise NotImplementedError


class ETFMasterSource(ABC):
    @abstractmethod
    def fetch_masters(self) -> list[ETFMaster]:
        raise NotImplementedError


class ETFNavSource(ABC):
    @abstractmethod
    def fetch_navs(self, trade_date: date | None = None) -> list[ETFNav]:
        raise NotImplementedError


class ETFHoldingSource(ABC):
    @abstractmethod
    def fetch_holdings(self, security_id: str, report_date: date | None = None) -> list[ETFHolding]:
        raise NotImplementedError


class IndexConstituentSource(ABC):
    @abstractmethod
    def fetch_constituents(
        self, index_id: str, effective_date: date | None = None
    ) -> list[IndexConstituent]:
        raise NotImplementedError

