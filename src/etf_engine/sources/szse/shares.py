import io
from datetime import date, datetime
from decimal import Decimal

import akshare as ak
import pandas as pd
import requests

from etf_engine.domain.enums import QualityStatus
from etf_engine.domain.models import ETFShare, SourceMeta
from etf_engine.sources.base import ETFShareSource


class SZSEETFShareSource(ETFShareSource):
    """通过 AKShare / SZSE 官方接口获取深交所 ETF 当前份额。

    当前接口主要用于最新快照。历史份额由本系统每日持续积累。
    """

    def _fetch_from_official(self) -> pd.DataFrame:
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
        resp.raise_for_status()
        df = pd.read_excel(io.BytesIO(resp.content), engine="openpyxl", dtype={"基金代码": str})
        df.rename(columns={"当前规模(份)": "基金份额"}, inplace=True)
        df["基金份额"] = df["基金份额"].astype(str).str.replace(",", "", regex=False)
        df["基金份额"] = pd.to_numeric(df["基金份额"], errors="coerce")
        df["净值"] = pd.to_numeric(df.get("净值"), errors="coerce")
        return df

    def fetch_shares(self, trade_date: date | None = None) -> list[ETFShare]:
        try:
            df = ak.fund_etf_scale_szse()
        except TypeError:
            # 兼容处理三方包中 read_excel 传入未 wrap 的 bytes 的 bug
            df = self._fetch_from_official()

        fetched_at = datetime.now().astimezone()
        effective_date = trade_date or fetched_at.date()
        result: list[ETFShare] = []


        for _, row in df.iterrows():
            nav = row.get("净值")
            result.append(
                ETFShare(
                    security_id=f"{str(row['基金代码']).zfill(6)}.SZ",
                    trade_date=effective_date,
                    fund_name=str(row["基金简称"]),
                    shares=Decimal(str(row["基金份额"])),
                    nav=None if pd.isna(nav) else Decimal(str(nav)),
                    source_meta=SourceMeta(
                        source="akshare",
                        upstream_source="szse",
                        fetched_at=fetched_at,
                        quality_status=QualityStatus.PASS,
                    ),
                )
            )

        return result
