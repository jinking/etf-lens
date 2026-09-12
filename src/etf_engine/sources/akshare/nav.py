import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

import akshare as ak
import pandas as pd

from etf_engine.domain.enums import QualityStatus
from etf_engine.domain.identifiers import SecurityId
from etf_engine.domain.models import ETFNav, SourceMeta
from etf_engine.domain.quality import DataQualityIssue, warn
from etf_engine.sources.base import ETFNavSource

#: 东方财富净值接口用列名携带日期，形如 ``2026-09-11-单位净值``。
_NAV_COLUMN = re.compile(r"^(\d{4}-\d{2}-\d{2})-(单位净值|累计净值)$")


def _decimal(value) -> Decimal | None:
    if value is None or pd.isna(value):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def parse_nav_frame(
    frame: pd.DataFrame,
    *,
    fetched_at: datetime,
    trade_date: date | None = None,
) -> tuple[list[ETFNav], list[DataQualityIssue]]:
    """把东方财富净值表解析成标准 ETFNav 事实。

    只落库 ``单位净值``；``累计净值`` 与复权净值口径不同，不做映射，
    ``adjusted_nav`` 保持 NULL（未知 ≠ 有值）。
    """
    navs: list[ETFNav] = []
    issues: list[DataQualityIssue] = []

    unit_nav_columns: dict[str, list[str]] = {}
    for column in frame.columns:
        match = _NAV_COLUMN.match(str(column))
        if match and match.group(2) == "单位净值":
            unit_nav_columns.setdefault(match.group(1), []).append(str(column))

    if not unit_nav_columns:
        raise RuntimeError("ETF NAV source returned no date-stamped 单位净值 columns.")

    for _, row in frame.iterrows():
        raw_code = str(row.get("基金代码", "")).strip()
        try:
            security_id = SecurityId.parse(raw_code).value
        except ValueError:
            issues.append(warn("nav_code_unresolved", f"基金代码={raw_code!r}"))
            continue

        for iso_date, columns in unit_nav_columns.items():
            nav_date = date.fromisoformat(iso_date)
            if trade_date is not None and nav_date != trade_date:
                continue
            unit_nav = _decimal(row.get(columns[0]))
            if unit_nav is None:
                continue
            if unit_nav <= 0:
                issues.append(
                    warn(
                        "nav_positive",
                        f"{security_id} {nav_date.isoformat()} unit_nav={unit_nav}",
                    )
                )
                continue
            navs.append(
                ETFNav(
                    security_id=security_id,
                    nav_date=nav_date,
                    unit_nav=unit_nav,
                    adjusted_nav=None,
                    source_meta=SourceMeta(
                        source="akshare",
                        upstream_source="eastmoney",
                        fetched_at=fetched_at,
                        quality_status=QualityStatus.PASS,
                    ),
                )
            )

    return navs, issues


class AkshareETFNavSource(ETFNavSource):
    """AKShare 场内基金净值适配器（上游事实来源：东方财富）。"""

    def fetch_navs(self, trade_date: date | None = None) -> list[ETFNav]:
        navs, _ = self.fetch_navs_with_issues(trade_date=trade_date)
        return navs

    def fetch_navs_with_issues(
        self, trade_date: date | None = None
    ) -> tuple[list[ETFNav], list[DataQualityIssue]]:
        fetched_at = datetime.now().astimezone()
        frame = ak.fund_etf_fund_daily_em()
        return parse_nav_frame(frame, fetched_at=fetched_at, trade_date=trade_date)
