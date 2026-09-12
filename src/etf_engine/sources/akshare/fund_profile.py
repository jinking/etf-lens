"""基金档案适配器（上游事实来源：东方财富基金概况页 fundf10）。

提供基金公司披露的静态档案：基金全称/简称、成立日期、管理人、托管人、
管理费率、托管费率、跟踪标的与业绩比较基准。

历史实现里沪市 ETF 的管理人、成立日期、费率全是 NULL——只有深交所官方列表
提供这部分字段。这个适配器让沪深两市都能拿到同一口径的档案事实。
"""

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import TypedDict, cast

import requests

from etf_engine.domain.enums import QualityStatus
from etf_engine.domain.identifiers import SecurityId
from etf_engine.domain.models import FundProfile, SourceMeta

FUND_PROFILE_URL = "https://fundf10.eastmoney.com/jbgk_{code}.html"

_ROW = re.compile(r"<th[^>]*>(.*?)</th>\s*<td[^>]*>(.*?)</td>", re.S)
_LABEL_SPAN = re.compile(r"<label>\s*成立日期：\s*<span[^>]*>(.*?)</span>", re.S)
_TAG = re.compile(r"<[^>]+>")
_ISO_DATE = re.compile(r"(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})")
_FEE = re.compile(r"(\d+(?:\.\d+)?)\s*%")


#: 档案页字段 → 模型字段。
class ParsedProfile(TypedDict, total=False):
    fund_name: str | None
    short_name: str | None
    fund_type: str | None
    established_date: date | None
    manager_name: str | None
    custodian_name: str | None
    management_fee_pct: Decimal | None
    custodian_fee_pct: Decimal | None
    tracking_target: str | None
    benchmark: str | None


_TEXT_FIELDS = {
    "基金全称": "fund_name",
    "基金简称": "short_name",
    "基金类型": "fund_type",
    "基金管理人": "manager_name",
    "基金托管人": "custodian_name",
    "跟踪标的": "tracking_target",
    "业绩比较基准": "benchmark",
}
_DATE_FIELD = "成立日期/规模"
_FEE_FIELDS = {"管理费率": "management_fee_pct", "托管费率": "custodian_fee_pct"}

#: "---" 之类的占位值表示上游未披露，必须留 NULL。
_PLACEHOLDERS = {"", "---", "--", "-", "nan", "None"}


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    text = _TAG.sub("", value).replace("&nbsp;", " ").strip()
    return None if text in _PLACEHOLDERS else text


def _parse_date(value: str | None) -> date | None:
    text = _clean(value)
    if not text:
        return None
    match = _ISO_DATE.search(text)
    if not match:
        return None
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


def _parse_fee(value: str | None) -> Decimal | None:
    text = _clean(value)
    if not text:
        return None
    match = _FEE.search(text)
    if not match:
        return None
    try:
        return Decimal(match.group(1))
    except InvalidOperation:
        return None


def parse_fund_profile(html: str) -> ParsedProfile:
    """把基金概况页解析成字段字典（纯函数，便于 fixture 测试）。"""
    rows: dict[str, str] = {}
    for label, value in _ROW.findall(html):
        key = _clean(label)
        if key and key not in rows:
            rows[key] = value

    # 内部用普通 dict 逐字段填充（TypedDict 只接受字面量键），返回前收窄类型。
    profile: dict[str, object] = {}
    for label, field in _TEXT_FIELDS.items():
        profile[field] = _clean(rows.get(label))

    established = None
    label_match = _LABEL_SPAN.search(html)
    if label_match:
        established = _parse_date(label_match.group(1))
    profile["established_date"] = established or _parse_date(rows.get(_DATE_FIELD))

    for label, field in _FEE_FIELDS.items():
        profile[field] = _parse_fee(rows.get(label))

    return cast(ParsedProfile, profile)


class AkshareFundProfileSource:
    """按基金取档案页。逐只请求，因此只应由有界限速的任务调用。"""

    source_name = "eastmoney"

    def fetch_profile(self, security_id: str) -> FundProfile:
        sid = SecurityId.parse(security_id)
        response = requests.get(
            FUND_PROFILE_URL.format(code=sid.ticker),
            headers={"User-Agent": "Mozilla/5.0"},
            timeout=20.0,
        )
        response.raise_for_status()
        fields = parse_fund_profile(response.text)
        return FundProfile(
            security_id=sid.value,
            source_meta=SourceMeta(
                source="eastmoney",
                upstream_source="eastmoney_fund_profile",
                fetched_at=datetime.now().astimezone(),
                quality_status=QualityStatus.PASS,
            ),
            **fields,
        )

    def fetch_benchmark(self, security_id: str) -> str | None:
        """跟踪指数候选文本：优先"跟踪标的"，缺失时退回"业绩比较基准"。"""
        profile = self.fetch_profile(security_id)
        return profile.tracking_target or profile.benchmark
