from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import re

import akshare as ak
import pandas as pd

from etf_engine.domain.enums import QualityStatus
from etf_engine.domain.identifiers import SecurityId
from etf_engine.domain.models import ETFHolding, SourceMeta
from etf_engine.sources.base import ETFHoldingSource


def _decimal(value):
    if value is None or pd.isna(value):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _parse_quarter_to_date(quarter_str: str) -> date:
    """将 '2024年1季度股票投资明细' 转换为 2024-03-31。"""
    match = re.search(r"(\d{4})年(\d)季度", str(quarter_str))
    if match:
        year = int(match.group(1))
        q = int(match.group(2))
        month_day = {1: (3, 31), 2: (6, 30), 3: (9, 30), 4: (12, 31)}.get(q, (12, 31))
        return date(year, month_day[0], month_day[1])
    return datetime.now().date()


class AkshareETFHoldingSource(ETFHoldingSource):
    """通过东方财富接口获取 ETF 披露持仓。"""

    def fetch_holdings(self, security_id: str, report_date: date | None = None) -> list[ETFHolding]:
        sid = SecurityId.parse(security_id)
        current_year = (report_date or datetime.now().date()).year

        # 优先拉取当前年份，若无则尝试前一年
        df = None
        for y in [str(current_year), str(current_year - 1), str(current_year - 2)]:
            try:
                temp_df = ak.fund_portfolio_hold_em(symbol=sid.ticker, date=y)
                if temp_df is not None and not temp_df.empty:
                    df = temp_df
                    break
            except Exception:
                continue

        if df is None or df.empty:
            return []

        # 按最新季度过滤前十大持仓
        latest_quarter = df["季度"].iloc[0]
        latest_df = df[df["季度"] == latest_quarter].head(10)
        actual_report_date = _parse_quarter_to_date(latest_quarter)

        fetched_at = datetime.now().astimezone()
        result: list[ETFHolding] = []

        for _, row in latest_df.iterrows():
            stock_code = str(row.get("股票代码", "")).strip().zfill(6)
            if not stock_code:
                continue

            stock_id = SecurityId.parse(stock_code).value
            weight = _decimal(row.get("占净值比例"))
            shares = _decimal(row.get("持股数"))
            market_value = _decimal(row.get("持仓市值"))

            result.append(
                ETFHolding(
                    etf_id=sid.value,
                    report_date=actual_report_date,
                    disclosure_date=actual_report_date,
                    stock_id=stock_id,
                    stock_name=str(row.get("股票名称", "")).strip() or None,
                    weight_pct=weight,
                    shares=shares,
                    market_value=market_value,
                    source_meta=SourceMeta(
                        source="akshare",
                        upstream_source="eastmoney",
                        fetched_at=fetched_at,
                        quality_status=QualityStatus.PASS,
                    ),
                )
            )

        return result
