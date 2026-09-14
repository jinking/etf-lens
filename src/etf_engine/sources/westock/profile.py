from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Sequence

import pandas as pd

from etf_engine.domain.enums import QualityStatus
from etf_engine.domain.identifiers import SecurityId
from etf_engine.domain.models import FundProfile, SourceMeta
from etf_engine.sources.westock.client import WestockClient
from etf_engine.sources.westock.symbols import to_security_id, to_westock_symbol


def _decimal(value) -> Decimal | None:
    if value is None or pd.isna(value) or str(value).strip() in ("", "-", "--"):
        return None
    try:
        return Decimal(str(value).replace(",", ""))
    except (InvalidOperation, ValueError):
        return None


def _parse_date(value: str | None) -> date | None:
    if not value or pd.isna(value) or str(value).strip() in ("", "-", "--"):
        return None
    try:
        return pd.Timestamp(str(value).split()[0]).date()
    except Exception:
        return None


class WestockETFProfileSource:
    """基于 WeStock (腾讯自选股源) 的 ETF 概况与披露规模/份额适配器。"""

    def __init__(self, client: WestockClient | None = None):
        self.client = client or WestockClient()

    def fetch_profile(self, security_id: str) -> FundProfile:
        """获取单个 ETF 的基本概况。"""
        canonical_id = SecurityId.parse(security_id).value
        symbol = to_westock_symbol(canonical_id)
        output = self.client.execute("etf", symbol)
        details = self.client.parse_etf_details(output)
        info = details.get("info", {})

        return FundProfile(
            security_id=canonical_id,
            fund_name=info.get("name"),
            short_name=info.get("name"),
            fund_type=info.get("etfType"),
            established_date=_parse_date(info.get("establishDate")),
            manager_name=info.get("manageInstitution"),
            custodian_name=info.get("trusteeInstitution"),
            management_fee_pct=_decimal(info.get("managementFee")),
            custodian_fee_pct=_decimal(info.get("custodyFee")),
            tracking_target=info.get("trackIndexName"),
            benchmark=None,
            source_meta=SourceMeta(
                source="westock",
                upstream_source="tencent",
                fetched_at=datetime.now().astimezone(),
                quality_status=QualityStatus.PASS,
            ),
        )

    def fetch_aum_and_shares(self, security_ids: Sequence[str]) -> list[dict]:
        """批量获取 ETF 的披露规模 (reported_aum) 和份额 (shares)。"""
        if not security_ids:
            return []

        batch_size = 20
        results: list[dict] = []
        fetched_at = datetime.now().astimezone()

        for i in range(0, len(security_ids), batch_size):
            chunk = security_ids[i : i + batch_size]
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

                asof_date = _parse_date(info.get("date")) or datetime.now().date()
                reported_aum = _decimal(info.get("size"))
                shares = _decimal(info.get("shares"))
                nav = _decimal(info.get("nav"))

                results.append(
                    {
                        "security_id": sid,
                        "fund_name": info.get("name"),
                        "fund_type": info.get("etfType"),
                        "trade_date": asof_date,
                        "reported_aum": reported_aum,
                        "reported_aum_date": asof_date,
                        "shares": shares,
                        "nav": nav,
                        "manager_name": info.get("manageInstitution"),
                        "custodian_name": info.get("trusteeInstitution"),
                        "fetched_at": fetched_at,
                    }
                )

        return results
