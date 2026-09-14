from datetime import date, datetime
from decimal import Decimal, InvalidOperation

import pandas as pd

from etf_engine.domain.enums import QualityStatus
from etf_engine.domain.identifiers import SecurityId
from etf_engine.domain.models import ETFHolding, SourceMeta
from etf_engine.sources.base import ETFHoldingSource
from etf_engine.sources.westock.client import WestockClient
from etf_engine.sources.westock.symbols import to_westock_symbol


def _decimal(value) -> Decimal | None:
    if value is None or pd.isna(value) or str(value).strip() in ("", "-", "--"):
        return None
    try:
        return Decimal(str(value).replace(",", ""))
    except (InvalidOperation, ValueError):
        return None


class WestockETFHoldingSource(ETFHoldingSource):
    """基于 WeStock (etf-holdings) 的 ETF 最新清单持仓明细适配器。"""

    def __init__(self, client: WestockClient | None = None):
        self.client = client or WestockClient()

    def fetch_holdings(
        self,
        security_id: str,
        report_date: date | None = None,
    ) -> list[ETFHolding]:
        sid = SecurityId.parse(security_id)
        westock_sym = to_westock_symbol(sid.value)

        output = self.client.execute("etf-holdings", westock_sym)
        rows, disclosure_str = self.client.parse_holdings(output)
        if not rows:
            return []

        disclosure_date = None
        if disclosure_str:
            try:
                disclosure_date = pd.Timestamp(disclosure_str).date()
            except Exception:
                pass

        final_report_date = report_date or disclosure_date
        fetched_at = datetime.now().astimezone()
        results: list[ETFHolding] = []

        for row in rows:
            raw_code = str(row.get("code", "")).strip()
            if not raw_code:
                continue

            try:
                stock_sid = SecurityId.parse(raw_code).value
            except ValueError:
                continue

            ratio_val = _decimal(row.get("ratio"))

            results.append(
                ETFHolding(
                    etf_id=sid.value,
                    report_date=final_report_date,
                    disclosure_date=disclosure_date,
                    stock_id=stock_sid,
                    stock_name=row.get("name"),
                    weight_pct=ratio_val,
                    shares=None,
                    market_value=None,
                    source_meta=SourceMeta(
                        source="westock",
                        upstream_source="tencent",
                        fetched_at=fetched_at,
                        quality_status=QualityStatus.PASS,
                    ),
                )
            )

        return results
