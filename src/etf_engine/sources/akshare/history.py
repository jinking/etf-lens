from datetime import date, datetime
from decimal import Decimal, InvalidOperation

import akshare as ak
import pandas as pd

from etf_engine.domain.enums import Exchange, QualityStatus
from etf_engine.domain.identifiers import SecurityId
from etf_engine.domain.models import ETFQuote, SourceMeta
from etf_engine.ingestion.retry import socket_timeout
from etf_engine.sources.base import ETFHistorySource

#: 新浪历史行情接口使用的小写市场前缀。
_SINA_PREFIX = {Exchange.SSE: "sh", Exchange.SZSE: "sz"}


def _decimal(value):
    if value is None or pd.isna(value):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


class AkshareETFHistorySource(ETFHistorySource):
    def _fetch_from_sina(self, sid: SecurityId, start_date: date, end_date: date) -> list[ETFQuote]:
        prefix = _SINA_PREFIX.get(sid.exchange)
        if prefix is None:
            raise ValueError(f"新浪历史行情接口不支持 {sid.exchange.value}")
        symbol = f"{prefix}{sid.ticker}"
        with socket_timeout():
            df = ak.fund_etf_hist_sina(symbol=symbol)
        fetched_at = datetime.now().astimezone()
        result: list[ETFQuote] = []
        if df is None or df.empty:
            return result

        df["date"] = pd.to_datetime(df["date"]).dt.date
        df = df[(df["date"] >= start_date) & (df["date"] <= end_date)]

        for _, row in df.iterrows():
            result.append(
                ETFQuote(
                    security_id=sid.value,
                    trade_date=row["date"],
                    open=_decimal(row.get("open")),
                    high=_decimal(row.get("high")),
                    low=_decimal(row.get("low")),
                    close=_decimal(row.get("close")),
                    volume=_decimal(row.get("volume")),
                    turnover_amount=_decimal(row.get("amount")),
                    source_meta=SourceMeta(
                        source="akshare",
                        upstream_source="sina",
                        fetched_at=fetched_at,
                        quality_status=QualityStatus.PASS,
                    ),
                )
            )
        return result

    def fetch_history(
        self,
        security_id: str,
        start_date: date,
        end_date: date,
    ) -> list[ETFQuote]:
        sid = SecurityId.parse(security_id)
        try:
            with socket_timeout():
                df = ak.fund_etf_hist_em(
                    symbol=sid.ticker,
                    period="daily",
                    start_date=start_date.strftime("%Y%m%d"),
                    end_date=end_date.strftime("%Y%m%d"),
                    adjust="",
                )
            fetched_at = datetime.now().astimezone()
            result: list[ETFQuote] = []

            for _, row in df.iterrows():
                result.append(
                    ETFQuote(
                        security_id=sid.value,
                        trade_date=pd.Timestamp(row["日期"]).date(),
                        open=_decimal(row.get("开盘")),
                        high=_decimal(row.get("最高")),
                        low=_decimal(row.get("最低")),
                        close=_decimal(row.get("收盘")),
                        change=_decimal(row.get("涨跌额")),
                        change_pct=_decimal(row.get("涨跌幅")),
                        volume=_decimal(row.get("成交量")),
                        turnover_amount=_decimal(row.get("成交额")),
                        turnover_rate=_decimal(row.get("换手率")),
                        amplitude=_decimal(row.get("振幅")),
                        source_meta=SourceMeta(
                            source="akshare",
                            upstream_source="eastmoney",
                            fetched_at=fetched_at,
                            quality_status=QualityStatus.PASS,
                        ),
                    )
                )
            return result
        except Exception:
            # 当东财接口被代理拦截或断开连接时，平滑回退至新浪接口
            return self._fetch_from_sina(sid, start_date, end_date)
