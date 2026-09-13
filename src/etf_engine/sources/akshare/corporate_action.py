"""ETF 公司行为适配器（上游事实来源：天天基金"分红送配"页）。

解析两张披露表：

```text
分红   年份 | 权益登记日 | 除息日 | 每10份分红 | 分红发放日
拆分   年份 | 拆分折算日 | 拆分类型 | 拆分折算比例
```

只有这两张表里写明的内容才算事实。价格跳变检测在
:mod:`etf_engine.research.corporate_actions`，它只用于"发现异常"，
不参与事实创建。
"""

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

import requests

from etf_engine.domain.enums import CorporateActionType, QualityStatus
from etf_engine.domain.identifiers import SecurityId
from etf_engine.domain.models import ETFCorporateAction, SourceMeta
from etf_engine.domain.quality import DataQualityIssue, warn
from etf_engine.ingestion.retry import socket_timeout
from etf_engine.sources.base import ETFCorporateActionSource

FUND_DIVIDEND_URL = "https://fundf10.eastmoney.com/fhsp_{code}.html"

_TABLE = re.compile(r"<table[^>]*>(.*?)</table>", re.S)
_ROW = re.compile(r"<tr[^>]*>(.*?)</tr>", re.S)
_CELL = re.compile(r"<t[dh][^>]*>(.*?)</t[dh]>", re.S)
_TAG = re.compile(r"<[^>]+>")
_RATIO = re.compile(r"^\s*([\d.]+)\s*[:：]\s*([\d.]+)\s*$")
#: "每10份派现金1.2300元" → 取"元"前面的金额，而不是"每10份"里的 10。
_CASH_AMOUNT = re.compile(r"([\d.]+)\s*元")
_ANY_NUMBER = re.compile(r"([\d.]+)")

DIVIDEND_HEADER = ("年份", "权益登记日", "除息日", "每10份分红", "分红发放日")
SPLIT_HEADER = ("年份", "拆分折算日", "拆分类型", "拆分折算比例")

#: 披露的"拆分类型"到标准枚举的映射。
SPLIT_TYPE_MAP = {
    "份额分拆": CorporateActionType.SPLIT,
    "份额合并": CorporateActionType.REVERSE_SPLIT,
    "份额折算": CorporateActionType.SHARE_CONVERSION,
    "基金折算": CorporateActionType.SHARE_CONVERSION,
}


def _clean(value: str) -> str:
    return _TAG.sub("", value).replace("&nbsp;", " ").strip()


def _table_rows(html: str) -> list[tuple[list[str], list[list[str]]]]:
    """抽出所有表格的 ``(表头, 数据行)``。"""
    tables: list[tuple[list[str], list[list[str]]]] = []
    for table in _TABLE.findall(html):
        rows = [_CELL.findall(row) for row in _ROW.findall(table)]
        rows = [[_clean(cell) for cell in row] for row in rows if row]
        if not rows:
            continue
        tables.append((rows[0], rows[1:]))
    return tables


def _parse_date(value: str) -> date | None:
    match = re.search(r"(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})", value)
    if not match:
        return None
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


def _parse_ratio(value: str) -> tuple[Decimal, Decimal] | None:
    """``1:2.0000`` → (share_factor=2, nav_factor=0.5)。"""
    match = _RATIO.match(value)
    if not match:
        return None
    try:
        left = Decimal(match.group(1))
        right = Decimal(match.group(2))
    except InvalidOperation:
        return None
    if left <= 0 or right <= 0:
        return None
    share_factor = right / left
    return share_factor, Decimal(1) / share_factor


def _aligned_row(row: list[str], header: list[str]) -> list[str] | None:
    """列数不足的行是上游的"暂无数据"占位，不是数据，直接跳过。

    实测：没有分红的基金，分红表只有一行 ``['暂无分红信息!']``——
    按表头取列会 IndexError，必须当成"无记录"而不是解析失败。
    """
    if len(row) != len(header):
        return None
    return row


def parse_corporate_action_tables(
    html: str,
    *,
    security_id: str,
    fetched_at: datetime,
) -> tuple[list[ETFCorporateAction], list[DataQualityIssue]]:
    """解析分红送配页，产出公司行为事实。"""
    actions: list[ETFCorporateAction] = []
    issues: list[DataQualityIssue] = []
    meta = SourceMeta(
        source="eastmoney",
        upstream_source="eastmoney_fund_dividend",
        fetched_at=fetched_at,
        quality_status=QualityStatus.PASS,
    )

    def _column(header: list[str], name: str) -> int | None:
        return header.index(name) if name in header else None

    for header, rows in _table_rows(html):
        if tuple(header) == SPLIT_HEADER:
            for raw_row in rows:
                row = _aligned_row(raw_row, header)
                if row is None:
                    continue
                action_date = _parse_date(row[1])
                if action_date is None:
                    issues.append(warn("corporate_action_date_invalid", f"{security_id} {row}"))
                    continue
                parsed = _parse_ratio(row[3])
                if parsed is None:
                    issues.append(
                        warn("corporate_action_ratio_invalid", f"{security_id} {row[3]!r}")
                    )
                    continue
                share_factor, nav_factor = parsed
                actions.append(
                    ETFCorporateAction(
                        security_id=security_id,
                        action_date=action_date,
                        action_type=SPLIT_TYPE_MAP.get(row[2], CorporateActionType.OTHER),
                        split_ratio=row[3],
                        nav_adjustment_factor=nav_factor,
                        share_adjustment_factor=share_factor,
                        source_meta=meta,
                    )
                )
        elif tuple(header) == DIVIDEND_HEADER:
            ex_index = _column(header, "除息日")
            cash_index = _column(header, "每10份分红")
            for raw_row in rows:
                row = _aligned_row(raw_row, header)
                if row is None:
                    continue
                action_date = _parse_date(row[ex_index]) if ex_index is not None else None
                if action_date is None:
                    issues.append(warn("corporate_action_date_invalid", f"{security_id} {row}"))
                    continue
                cash_text = row[cash_index] if cash_index is not None else ""
                cash_values = _CASH_AMOUNT.findall(cash_text) or _ANY_NUMBER.findall(cash_text)
                if not cash_values:
                    issues.append(warn("corporate_action_cash_invalid", f"{security_id} {row}"))
                    continue
                try:
                    # 取最后一个数字：文本是"每10份派现金1.2300元"，
                    # 前面的 10 是份额基准，不是金额。
                    cash_per_unit = Decimal(cash_values[-1]) / Decimal(10)
                except InvalidOperation:
                    issues.append(warn("corporate_action_cash_invalid", f"{security_id} {row}"))
                    continue
                actions.append(
                    ETFCorporateAction(
                        security_id=security_id,
                        action_date=action_date,
                        action_type=CorporateActionType.DIVIDEND,
                        cash_distribution=cash_per_unit,
                        source_meta=meta,
                    )
                )

    actions.sort(key=lambda item: item.action_date)
    return actions, issues


class EastmoneyFundActionSource(ETFCorporateActionSource):
    """按基金取分红送配披露（逐只请求，因此只应由有界限速的任务调用）。"""

    source_name = "eastmoney"

    def fetch_corporate_actions_with_issues(
        self, security_id: str
    ) -> tuple[list[ETFCorporateAction], list[DataQualityIssue]]:
        sid = SecurityId.parse(security_id)
        fetched_at = datetime.now().astimezone()
        with socket_timeout():
            response = requests.get(
                FUND_DIVIDEND_URL.format(code=sid.ticker),
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=20.0,
            )
        response.raise_for_status()
        return parse_corporate_action_tables(
            response.text, security_id=sid.value, fetched_at=fetched_at
        )

    def fetch_corporate_actions(self, security_id: str) -> list[ETFCorporateAction]:
        actions, _ = self.fetch_corporate_actions_with_issues(security_id)
        return actions
