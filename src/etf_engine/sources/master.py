import io
from datetime import date, datetime
from decimal import Decimal

import akshare as ak
import pandas as pd
import requests

from etf_engine.domain.enums import QualityStatus
from etf_engine.domain.identifiers import SecurityId
from etf_engine.domain.models import ETFMaster, SourceMeta
from etf_engine.sources.base import ETFMasterSource


class UnifiedETFMasterSource(ETFMasterSource):
    """综合全市场 ETF 基础资料适配器。

    整合深交所官方披露的详细档案（管理人、托管人、上市日期、类别）
    与全市场 ETF 列表（同花顺 / 上交所），生成标准化的全市场 ETF 档案事实。
    """

    def _fetch_szse_details(self) -> dict[str, dict]:
        details: dict[str, dict] = {}
        try:
            url = "https://fund.szse.cn/api/report/ShowReport"
            params = {
                "SHOWTYPE": "xlsx",
                "CATALOGID": "1000_lf",
                "TABKEY": "tab1",
                "random": "0.07610353191740105",
            }
            headers = {
                "Referer": "https://fund.szse.cn/marketdata/fundslist/index.html",
                "User-Agent": "Mozilla/5.0",
            }
            resp = requests.get(url, params=params, headers=headers, timeout=15)
            if resp.status_code == 200:
                df = pd.read_excel(io.BytesIO(resp.content), engine="openpyxl", dtype={"基金代码": str})
                for _, row in df.iterrows():
                    code = str(row.get("基金代码", "")).strip().zfill(6)
                    if not code:
                        continue
                    sid = f"{code}.SZ"
                    listed_date = None
                    if "上市日期" in row and not pd.isna(row["上市日期"]):
                        try:
                            listed_date = pd.to_datetime(row["上市日期"]).date()
                        except Exception:
                            listed_date = None
                    details[sid] = {
                        "short_name": None if pd.isna(row.get("基金简称")) else str(row.get("基金简称")),
                        "fund_type": None if pd.isna(row.get("基金类别")) else str(row.get("基金类别")),
                        "investment_type": None if pd.isna(row.get("投资类别")) else str(row.get("投资类别")),
                        "manager_name": None if pd.isna(row.get("基金管理人")) else str(row.get("基金管理人")),
                        "custodian_name": None if pd.isna(row.get("基金托管人")) else str(row.get("基金托管人")),
                        "listed_date": listed_date,
                    }
        except Exception:
            pass
        return details

    def fetch_masters(self) -> list[ETFMaster]:
        fetched_at = datetime.now().astimezone()
        szse_details = self._fetch_szse_details()

        all_records: dict[str, ETFMaster] = {}
        try:
            ths_df = ak.fund_etf_category_ths(symbol="ETF")
            for _, row in ths_df.iterrows():
                code_raw = str(row.get("基金代码", "")).strip().zfill(6)
                if not code_raw or not code_raw.isdigit():
                    continue
                try:
                    sec_id = SecurityId.parse(code_raw)
                except ValueError:
                    continue
                sid = sec_id.value
                fund_name = str(row.get("基金名称", "")).strip() or None
                fund_type = str(row.get("基金类型", "")).strip() or None

                detail = szse_details.get(sid, {})
                all_records[sid] = ETFMaster(
                    security_id=sid,
                    ticker=sec_id.ticker,
                    exchange=sec_id.exchange.value,
                    fund_name=fund_name,
                    short_name=detail.get("short_name") or fund_name,
                    fund_type=detail.get("fund_type") or fund_type,
                    investment_type=detail.get("investment_type"),
                    manager_name=detail.get("manager_name"),
                    custodian_name=detail.get("custodian_name"),
                    listed_date=detail.get("listed_date"),
                    status="ACTIVE",
                    source_meta=SourceMeta(
                        source="akshare",
                        upstream_source="ths_szse",
                        fetched_at=fetched_at,
                        quality_status=QualityStatus.PASS,
                    ),
                )
        except Exception:
            pass

        for sid, detail in szse_details.items():
            if sid not in all_records:
                sec_id = SecurityId.parse(sid)
                all_records[sid] = ETFMaster(
                    security_id=sid,
                    ticker=sec_id.ticker,
                    exchange=sec_id.exchange.value,
                    fund_name=detail.get("short_name"),
                    short_name=detail.get("short_name"),
                    fund_type=detail.get("fund_type"),
                    investment_type=detail.get("investment_type"),
                    manager_name=detail.get("manager_name"),
                    custodian_name=detail.get("custodian_name"),
                    listed_date=detail.get("listed_date"),
                    status="ACTIVE",
                    source_meta=SourceMeta(
                        source="szse",
                        upstream_source="official",
                        fetched_at=fetched_at,
                        quality_status=QualityStatus.PASS,
                    ),
                )

        return list(all_records.values())
