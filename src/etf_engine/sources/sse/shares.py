from datetime import date, datetime, timedelta
from decimal import Decimal

import akshare as ak
import pandas as pd

from etf_engine.domain.enums import QualityStatus
from etf_engine.domain.models import ETFShare, SourceMeta
from etf_engine.sources.base import ETFShareSource


class SSEETFShareSource(ETFShareSource):
    """通过 AKShare wrapper 获取上交所 ETF 份额。

    上游事实来源：SSE。
    """

    def fetch_shares(self, trade_date: date | None = None) -> list[ETFShare]:
        df = None
        if trade_date is not None:
            # 如果指定了具体日期，先尝试该日期，如遇非交易日则回退至最近工作日（最多回退3天）
            curr_date = trade_date
            for _ in range(4):
                try:
                    df = ak.fund_etf_scale_sse(date=curr_date.strftime("%Y%m%d"))
                    if df is not None and not df.empty:
                        break
                except Exception:
                    curr_date = curr_date - timedelta(days=1)
        if df is None or df.empty:
            try:
                df = ak.fund_etf_scale_sse()
            except Exception:
                df = pd.DataFrame()

        fetched_at = datetime.now().astimezone()
        result: list[ETFShare] = []
        if df.empty:
            return result


        for _, row in df.iterrows():
            row_date = pd.Timestamp(row["统计日期"]).date()
            result.append(
                ETFShare(
                    security_id=f"{str(row['基金代码']).zfill(6)}.SH",
                    trade_date=row_date,
                    fund_name=str(row["基金简称"]),
                    shares=Decimal(str(row["基金份额"])),
                    source_meta=SourceMeta(
                        source="akshare",
                        upstream_source="sse",
                        fetched_at=fetched_at,
                        quality_status=QualityStatus.PASS,
                    ),
                )
            )
        return result
