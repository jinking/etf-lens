from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Sequence

import pandas as pd

from etf_engine.domain.enums import QualityStatus
from etf_engine.domain.identifiers import SecurityId
from etf_engine.domain.models import ETFNav, SourceMeta
from etf_engine.sources.base import ETFNavHistorySource, ETFNavSource
from etf_engine.sources.westock.client import WestockClient
from etf_engine.sources.westock.symbols import to_westock_symbol


def _decimal(value) -> Decimal | None:
    if value is None or pd.isna(value) or str(value).strip() in ("", "-", "--"):
        return None
    try:
        return Decimal(str(value).replace(",", ""))
    except (InvalidOperation, ValueError):
        return None


class WestockETFNavSource(ETFNavSource):
    """基于 WeStock 的最新净值适配器。"""

    def __init__(self, client: WestockClient | None = None):
        self.client = client or WestockClient()

    def fetch_navs(
        self,
        trade_date: date | None = None,
        security_ids: Sequence[str] | None = None,
    ) -> list[ETFNav]:
        if not security_ids:
            return []

        fetched_at = datetime.now().astimezone()
        results: list[ETFNav] = []

        for sid_str in security_ids:
            try:
                westock_sym = to_westock_symbol(sid_str)
                output = self.client.execute("etf", westock_sym)
                details = self.client.parse_etf_details(output)
                info = details.get("info", {})
                if not info or not info.get("nav"):
                    continue

                row_date = trade_date
                if row_date is None and info.get("date"):
                    row_date = pd.Timestamp(info["date"]).date()

                results.append(
                    ETFNav(
                        security_id=SecurityId.parse(sid_str).value,
                        nav_date=row_date or datetime.now().date(),
                        unit_nav=_decimal(info.get("nav")),
                        adjusted_nav=None,
                        source_meta=SourceMeta(
                            source="westock",
                            upstream_source="tencent",
                            fetched_at=fetched_at,
                            quality_status=QualityStatus.PASS,
                        ),
                    )
                )
            except Exception:
                continue

        return results


class WestockETFNavHistorySource(ETFNavHistorySource):
    """基于 WeStock 的历史净值适配器 (etf-nav)。"""

    def __init__(self, client: WestockClient | None = None):
        self.client = client or WestockClient()

    def fetch_nav_history(
        self,
        security_id: str,
        start_date: date,
        end_date: date,
    ) -> list[ETFNav]:
        sid = SecurityId.parse(security_id)
        westock_sym = to_westock_symbol(sid.value)

        output = self.client.execute(
            "etf-nav",
            westock_sym,
            "--start",
            start_date.isoformat(),
            "--end",
            end_date.isoformat(),
        )
        rows = self.client.parse_markdown_table(output)
        if not rows:
            return []

        fetched_at = datetime.now().astimezone()
        results: list[ETFNav] = []

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

            unit_nav = _decimal(row.get("nav"))
            if unit_nav is None:
                continue

            results.append(
                ETFNav(
                    security_id=sid.value,
                    nav_date=row_date,
                    unit_nav=unit_nav,
                    adjusted_nav=None,
                    source_meta=SourceMeta(
                        source="westock",
                        upstream_source="tencent",
                        fetched_at=fetched_at,
                        quality_status=QualityStatus.PASS,
                    ),
                )
            )

        results.sort(key=lambda n: n.nav_date)
        return results
