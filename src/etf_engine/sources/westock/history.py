from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import math

import pandas as pd

from etf_engine.domain.enums import QualityStatus
from etf_engine.domain.identifiers import SecurityId
from etf_engine.domain.models import ETFQuote, SourceMeta
from etf_engine.sources.base import ETFHistorySource
from etf_engine.sources.westock.client import WestockClient
from etf_engine.sources.westock.symbols import to_westock_symbol


def _decimal(value) -> Decimal | None:
    if value is None or pd.isna(value) or str(value).strip() in ("", "-", "--"):
        return None
    try:
        return Decimal(str(value).replace(",", ""))
    except (InvalidOperation, ValueError):
        return None


class WestockETFHistorySource(ETFHistorySource):
    """基于 WeStock (腾讯自选股源) 的 ETF 历史日K行情适配器。"""

    def __init__(self, client: WestockClient | None = None):
        self.client = client or WestockClient()

    def fetch_history(
        self,
        security_id: str,
        start_date: date,
        end_date: date,
    ) -> list[ETFQuote]:
        sid = SecurityId.parse(security_id)
        westock_sym = to_westock_symbol(sid.value)

        # 估算需要拉取的日K条数 (自然日天数 + 缓冲)
        days = max((end_date - start_date).days + 15, 30)
        limit = min(days, 1000)

        output = self.client.execute("kline", westock_sym, "--period", "day", "--limit", str(limit))
        rows = self.client.parse_markdown_table(output)
        if not rows:
            return []

        fetched_at = datetime.now().astimezone()
        results: list[ETFQuote] = []

        for row in rows:
            raw_date = row.get("date")
            if not raw_date:
                continue
            try:
                row_date = pd.Timestamp(raw_date).date()
            except Exception:
                continue

            if not (start_date <= row_date <= end_date):
                continue

            results.append(
                ETFQuote(
                    security_id=sid.value,
                    trade_date=row_date,
                    open=_decimal(row.get("open")),
                    close=_decimal(row.get("last")),
                    high=_decimal(row.get("high")),
                    low=_decimal(row.get("low")),
                    volume=_decimal(row.get("volume")),
                    turnover_amount=_decimal(row.get("amount")),
                    source_meta=SourceMeta(
                        source="westock",
                        upstream_source="tencent",
                        fetched_at=fetched_at,
                        quality_status=QualityStatus.PASS,
                    ),
                )
            )

        # 按日期升序排列
        results.sort(key=lambda q: q.trade_date)
        return results
