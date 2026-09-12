from datetime import date, datetime
from decimal import Decimal, InvalidOperation

import akshare as ak
import pandas as pd

from etf_engine.domain.enums import QualityStatus
from etf_engine.domain.identifiers import SecurityId
from etf_engine.domain.models import ETFQuote, SourceMeta
from etf_engine.ingestion.normalizer import normalize_premium_discount
from etf_engine.sources.base import ETFQuoteSource


def _decimal(value):
    if value is None or pd.isna(value):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


class AkshareETFQuoteSource(ETFQuoteSource):
    """AKShare ETF 全市场行情适配器。

    注意：AKShare 是聚合层，`upstream_source` 标记为 eastmoney。
    """

    def fetch_quotes(self, trade_date: date | None = None) -> list[ETFQuote]:
        df = ak.fund_etf_spot_em()
        fetched_at = datetime.now().astimezone()
        result: list[ETFQuote] = []

        for _, row in df.iterrows():
            ticker = str(row["代码"]).zfill(6)
            sid = SecurityId.parse(ticker).value

            row_date = trade_date
            if row_date is None and "数据日期" in row and not pd.isna(row["数据日期"]):
                row_date = pd.Timestamp(row["数据日期"]).date()
            row_date = row_date or fetched_at.date()

            result.append(
                ETFQuote(
                    security_id=sid,
                    trade_date=row_date,
                    name=None if pd.isna(row.get("名称")) else str(row.get("名称")),
                    open=_decimal(row.get("开盘价")),
                    high=_decimal(row.get("最高价")),
                    low=_decimal(row.get("最低价")),
                    close=_decimal(row.get("最新价")),
                    prev_close=_decimal(row.get("昨收")),
                    change=_decimal(row.get("涨跌额")),
                    change_pct=_decimal(row.get("涨跌幅")),
                    volume=_decimal(row.get("成交量")),
                    turnover_amount=_decimal(row.get("成交额")),
                    turnover_rate=_decimal(row.get("换手率")),
                    amplitude=_decimal(row.get("振幅")),
                    iopv=_decimal(row.get("IOPV实时估值")),
                    premium_discount_pct=_decimal(row.get("基金折价率")),
                    premium_discount_pct_normalized=_decimal(
                        normalize_premium_discount(
                            float(row.get("最新价")) if not pd.isna(row.get("最新价")) else None,
                            float(row.get("IOPV实时估值"))
                            if not pd.isna(row.get("IOPV实时估值"))
                            else None,
                        )
                    ),
                    bid1=_decimal(row.get("买一")),
                    ask1=_decimal(row.get("卖一")),
                    bid1_volume=_decimal(row.get("买一量")),
                    ask1_volume=_decimal(row.get("卖一量")),
                    trading_flow_main=_decimal(row.get("主力净流入-净额")),
                    trading_flow_super_large=_decimal(row.get("超大单净流入-净额")),
                    trading_flow_large=_decimal(row.get("大单净流入-净额")),
                    trading_flow_medium=_decimal(row.get("中单净流入-净额")),
                    trading_flow_small=_decimal(row.get("小单净流入-净额")),
                    source_meta=SourceMeta(
                        source="akshare",
                        upstream_source="eastmoney",
                        fetched_at=fetched_at,
                        quality_status=QualityStatus.PASS,
                    ),
                )
            )

        return result
