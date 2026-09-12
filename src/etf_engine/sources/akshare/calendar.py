from datetime import date

import akshare as ak
import pandas as pd

from etf_engine.ingestion.retry import socket_timeout
from etf_engine.sources.base import TradingCalendarSource


class AkshareTradingCalendarSource(TradingCalendarSource):
    """AKShare 聚合的 A 股交易日历（上游事实来源：新浪财经）。"""

    upstream_source = "sina"

    def fetch_trading_days(self, start_date: date, end_date: date) -> list[date]:
        with socket_timeout():
            frame = ak.tool_trade_date_hist_sina()
        if frame is None or frame.empty or "trade_date" not in frame.columns:
            raise RuntimeError("Trading calendar source returned no 'trade_date' column.")

        days = pd.to_datetime(frame["trade_date"], errors="coerce").dt.date.dropna()
        return sorted(day for day in days if start_date <= day <= end_date)
