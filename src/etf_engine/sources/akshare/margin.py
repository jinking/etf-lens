"""融资融券余额（沪市 / 深市）。

两个市场由两个上游接口提供，口径与字段并不完全一致（深市的融券量有时为空），
因此**分列存储**，合计留到 mart 里派生，不在适配器里合并成一条"市场总量"。
"""

from datetime import date, datetime
from decimal import Decimal

import akshare as ak
import pandas as pd

from etf_engine.domain.enums import Exchange, QualityStatus
from etf_engine.domain.models import MarginBalance, SourceMeta
from etf_engine.domain.quality import DataQualityIssue, warn
from etf_engine.sources.base import MarginBalanceSource


def _decimal(value) -> Decimal | None:
    if value is None or pd.isna(value):
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def parse_margin_frame(
    frame: pd.DataFrame,
    *,
    exchange: Exchange,
    fetched_at: datetime,
    start_date: date | None = None,
    end_date: date | None = None,
) -> tuple[list[MarginBalance], list[DataQualityIssue]]:
    """解析两融余额历史表。

    缺列直接报错（上游改版必须立刻可见）；缺值保持 NULL，不填 0。
    """
    for column in ("日期", "融资余额", "融资融券余额"):
        if column not in frame.columns:
            raise RuntimeError(f"两融数据缺少 {column} 列")

    rows: list[MarginBalance] = []
    issues: list[DataQualityIssue] = []
    for _, row in frame.iterrows():
        try:
            trade_date = pd.Timestamp(row["日期"]).date()
        except (ValueError, TypeError):
            issues.append(warn("margin_date_invalid", f"{exchange} 日期={row['日期']!r}"))
            continue
        if start_date is not None and trade_date < start_date:
            continue
        if end_date is not None and trade_date > end_date:
            continue
        balance = _decimal(row.get("融资融券余额"))
        if balance is None:
            issues.append(warn("margin_balance_null", f"{exchange} {trade_date} 融资融券余额为空"))
            continue
        if balance <= 0:
            # 上游偶尔把缺失写成 0（实测 2024-08-08 深市）。0 不是事实：
            # 一个市场的两融余额不可能归零，落库只会污染合计与分位，
            # 因此记 issue 后跳过——这正是自检规则 zero_substituted_for_unknown 盯的形态。
            issues.append(
                warn(
                    "margin_balance_zero_substituted",
                    f"{exchange} {trade_date} 融资融券余额={balance}（上游用 0 顶替缺失）",
                )
            )
            continue
        rows.append(
            MarginBalance(
                trade_date=trade_date,
                exchange=exchange,
                financing_balance=_decimal(row.get("融资余额")),
                financing_buy_amount=_decimal(row.get("融资买入额")),
                securities_lending_balance=_decimal(row.get("融券余额")),
                margin_balance=balance,
                source_meta=SourceMeta(
                    source=f"akshare_margin_{exchange.value.lower()}",
                    upstream_source="exchange",
                    fetched_at=fetched_at,
                    quality_status=QualityStatus.PASS,
                ),
            )
        )
    return rows, issues


class AkshareMarginBalanceSource(MarginBalanceSource):
    """沪深两融余额。

    上游接口一次返回全量历史（各约 4000 行），因此按需切片，
    不做逐日请求——这也是它能放进日常同步链路的原因。
    """

    source_name = "akshare_margin"

    #: 交易所 → 上游函数。
    _FETCHERS = {
        Exchange.SSE: "macro_china_market_margin_sh",
        Exchange.SZSE: "macro_china_market_margin_sz",
    }

    def fetch_margin(
        self, start_date: date, end_date: date
    ) -> tuple[list[MarginBalance], list[DataQualityIssue]]:
        fetched_at = datetime.now().astimezone()
        rows: list[MarginBalance] = []
        issues: list[DataQualityIssue] = []

        for exchange, function_name in self._FETCHERS.items():
            try:
                frame = getattr(ak, function_name)()
            except Exception as exc:
                issues.append(warn("margin_fetch_failed", f"{exchange} ({function_name}): {exc}"))
                continue
            try:
                parsed, parse_issues = parse_margin_frame(
                    frame,
                    exchange=exchange,
                    fetched_at=fetched_at,
                    start_date=start_date,
                    end_date=end_date,
                )
            except RuntimeError as exc:
                issues.append(warn("margin_schema_changed", str(exc)))
                continue
            rows.extend(parsed)
            issues.extend(parse_issues)

        return rows, issues
