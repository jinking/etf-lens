from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Sequence

import pandas as pd

from etf_engine.domain.enums import QualityStatus
from etf_engine.domain.identifiers import SecurityId
from etf_engine.domain.models import ETFQuote, SourceMeta
from etf_engine.ingestion.normalizer import normalize_premium_discount
from etf_engine.repositories.master_repository import MasterRepository
from etf_engine.sources.base import ETFQuoteSource
from etf_engine.sources.westock.client import WestockClient
from etf_engine.sources.westock.symbols import to_security_id, to_westock_symbol


def _decimal(value) -> Decimal | None:
    if value is None or pd.isna(value) or str(value).strip() in ("", "-", "--"):
        return None
    try:
        return Decimal(str(value).replace(",", ""))
    except (InvalidOperation, ValueError):
        return None


class WestockETFQuoteSource(ETFQuoteSource):
    """基于 WeStock (腾讯自选股源) 的 ETF 行情适配器。"""

    def __init__(self, client: WestockClient | None = None):
        self.client = client or WestockClient()

    def fetch_quotes(
        self,
        trade_date: date | None = None,
        security_ids: Sequence[str] | None = None,
    ) -> list[ETFQuote]:
        """批量获取指定或全量 ETF 最新行情快照。"""
        targets: list[str] = []
        if security_ids:
            targets = list(security_ids)
        else:
            # 默认从本地 Master 获取标的
            targets = MasterRepository().all_security_ids()

        if not targets:
            return []

        # 转换为 westock 代码并按批次 (每批20只) 抓取
        batch_size = 20
        results: list[ETFQuote] = []
        fetched_at = datetime.now().astimezone()

        for i in range(0, len(targets), batch_size):
            chunk = targets[i : i + batch_size]
            symbols = []
            for item in chunk:
                try:
                    symbols.append(to_westock_symbol(item))
                except ValueError:
                    continue

            if not symbols:
                continue

            arg = ",".join(symbols)
            try:
                output = self.client.execute("etf", arg)
            except Exception:
                continue

            # 每个标的在输出中以 "#### sh510300" 类似的分隔符划分
            chunks = output.split("#### ")
            for block in chunks:
                block = block.strip()
                if not block:
                    continue
                first_line = block.splitlines()[0].strip()
                try:
                    sid = to_security_id(first_line)
                except ValueError:
                    continue

                details = self.client.parse_etf_details("#### " + block)
                info = details.get("info", {})
                if not info:
                    continue

                row_date = trade_date
                if row_date is None and info.get("date"):
                    try:
                        row_date = pd.Timestamp(info["date"]).date()
                    except Exception:
                        pass

                close_val = _decimal(info.get("closePrice"))
                iopv_val = _decimal(info.get("nav"))
                disc_val = _decimal(info.get("disc"))
                norm_disc = normalize_premium_discount(
                    float(close_val) if close_val is not None else None,
                    float(iopv_val) if iopv_val is not None else None,
                )

                results.append(
                    ETFQuote(
                        security_id=sid,
                        trade_date=row_date or datetime.now().date(),
                        name=info.get("name"),
                        close=close_val,
                        change_pct=_decimal(info.get("changePct")),
                        volume=_decimal(info.get("turnoverVolume")),
                        turnover_amount=_decimal(info.get("turnoverValue")),
                        turnover_rate=_decimal(info.get("turnoverRate")),
                        iopv=iopv_val,
                        premium_discount_pct=disc_val,
                        premium_discount_pct_normalized=_decimal(norm_disc),
                        source_meta=SourceMeta(
                            source="westock",
                            upstream_source="tencent",
                            fetched_at=fetched_at,
                            quality_status=QualityStatus.PASS,
                        ),
                    )
                )

        return results
