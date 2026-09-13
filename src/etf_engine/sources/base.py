from abc import ABC, abstractmethod
from datetime import date

from etf_engine.domain.enums import Exchange
from etf_engine.domain.models import (
    ETFCorporateAction,
    ETFHolding,
    ETFMaster,
    ETFNav,
    ETFQuote,
    ETFShare,
    FundIssuance,
    IndexConstituent,
    IndexValuation,
    MarginBalance,
    MarketActivity,
    MarketTurnover,
    MarketValuation,
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


class ETFNavHistorySource(ABC):
    """按基金逐个拉取净值历史。

    净值历史没有"全市场一次拉完"的接口，只能逐只基金请求；因此该能力被设计成
    独立接口，由回补任务有界、限速地调用，不能放在日常同步链路里。
    """

    @abstractmethod
    def fetch_nav_history(self, security_id: str, start_date: date, end_date: date) -> list[ETFNav]:
        raise NotImplementedError

    def fetch_nav_history_with_issues(
        self, security_id: str, start_date: date, end_date: date
    ) -> tuple[list[ETFNav], list[DataQualityIssue]]:
        return self.fetch_nav_history(security_id, start_date, end_date), []


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


class ETFCorporateActionSource(ABC):
    """公司行为能力接口（拆分 / 折算 / 分红）。

    只允许返回**披露来源**的事实。价格跳变检测属于"发现异常"，
    不允许用它来创建公司行为事实——一次数据错误会被固化成永久的错误口径。
    """

    @abstractmethod
    def fetch_corporate_actions(self, security_id: str) -> list[ETFCorporateAction]:
        raise NotImplementedError

    def fetch_corporate_actions_with_issues(
        self, security_id: str
    ) -> tuple[list[ETFCorporateAction], list[DataQualityIssue]]:
        return self.fetch_corporate_actions(security_id), []


class MarketTurnoverSource(ABC):
    """交易所每日概况能力：成交额、换手率、市值。

    一个来源只负责一个交易所（口径互不混用），合计由 mart 派生。
    """

    #: 该适配器负责的交易所。
    exchange: Exchange
    source_name: str = "unknown"

    @abstractmethod
    def fetch_turnover(self, trade_date: date) -> MarketTurnover | None:
        raise NotImplementedError

    def fetch_turnover_with_issues(
        self, trade_date: date
    ) -> tuple[list[MarketTurnover], list[DataQualityIssue]]:
        turnover = self.fetch_turnover(trade_date)
        return ([turnover] if turnover is not None else []), []


class MarginBalanceSource(ABC):
    """两融余额能力（按市场分列，逐交易日）。"""

    source_name: str = "unknown"

    @abstractmethod
    def fetch_margin(
        self, start_date: date, end_date: date
    ) -> tuple[list[MarginBalance], list[DataQualityIssue]]:
        raise NotImplementedError


class MarketValuationSource(ABC):
    """估值与历史分位能力。"""

    source_name: str = "unknown"

    @abstractmethod
    def fetch_valuation(
        self, start_date: date | None = None
    ) -> tuple[list[MarketValuation], list[DataQualityIssue]]:
        raise NotImplementedError


class MarketActivitySource(ABC):
    """涨跌家数 / 涨跌停 / 活跃度能力。"""

    source_name: str = "unknown"

    @abstractmethod
    def fetch_activity(
        self, trade_date: date | None = None
    ) -> tuple[list[MarketActivity], list[DataQualityIssue]]:
        raise NotImplementedError


class IndexValuationSource(ABC):
    """单条指数的估值序列能力（月度 PE 等）。

    只覆盖上游有序列的指数；没有序列的指数如实记 issue，
    不用"相近指数"或"用 ETF 的 PE 代替"顶替。
    """

    source_name: str = "unknown"

    @abstractmethod
    def fetch_index_valuations(
        self, index_ids: list[str]
    ) -> tuple[list[IndexValuation], list[DataQualityIssue]]:
        raise NotImplementedError


class FundIssuanceSource(ABC):
    """新发基金能力（场外增量资金的代理指标）。

    上游一次返回全量列表（含成立日期与募集份额），因此按"全量覆盖式写入"处理，
    不做逐只请求。
    """

    source_name: str = "unknown"

    @abstractmethod
    def fetch_issuances(self) -> tuple[list[FundIssuance], list[DataQualityIssue]]:
        raise NotImplementedError
