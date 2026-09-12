"""新发基金（东财口径）：成立日期 + 募集份额。

这是"场外增量资金"的代理指标——文档 1.2 的四个市场层指标之一。
上游一次给全量列表（约 6800 行、将近 7 秒），所以放在低频链路里跑。

口径纪律：
* 募集份额单位是**亿元**，原样落库，不换算成元（这一层的对比都是同量级）；
* 没有募集份额的行保留 NULL，不用 0 顶替（未知 ≠ 0）；
* 没有成立日期的行照常入库，但不参与月度聚合。
"""

from datetime import datetime
from decimal import Decimal, InvalidOperation

import akshare as ak
import pandas as pd

from etf_engine.domain.enums import QualityStatus
from etf_engine.domain.models import FundIssuance, SourceMeta
from etf_engine.domain.quality import DataQualityIssue, warn
from etf_engine.sources.base import FundIssuanceSource

#: 上游中文列 → 库内字段。
_COLUMNS = {
    "基金代码": "fund_code",
    "基金简称": "fund_name",
    "发行公司": "company",
    "基金类型": "fund_type",
    "集中认购期": "subscription_period",
    "募集份额": "raised_shares",
    "成立日期": "established_date",
    "基金经理": "manager",
}


def _decimal(value) -> Decimal | None:
    if value is None or pd.isna(value):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _date(value):
    if value is None or pd.isna(value):
        return None
    try:
        return pd.Timestamp(value).date()
    except (ValueError, TypeError):
        return None


def parse_fund_issuance_frame(
    frame: pd.DataFrame,
    *,
    fetched_at: datetime,
) -> tuple[list[FundIssuance], list[DataQualityIssue]]:
    for column in ("基金代码", "成立日期"):
        if column not in frame.columns:
            raise RuntimeError(f"新发基金数据缺少 {column} 列")

    rows: list[FundIssuance] = []
    issues: list[DataQualityIssue] = []
    for _, row in frame.iterrows():
        code = str(row["基金代码"]).strip()
        if not code or code.lower() == "nan":
            issues.append(warn("fund_issuance_code_missing", "新发基金缺少基金代码"))
            continue
        values = {
            target: row.get(source) for source, target in _COLUMNS.items() if target != "fund_code"
        }
        values["raised_shares"] = _decimal(values["raised_shares"])
        values["established_date"] = _date(values["established_date"])
        text_values = {
            key: (None if value is None or pd.isna(value) else str(value).strip())
            for key, value in values.items()
            if key not in {"raised_shares", "established_date"}
        }
        rows.append(
            FundIssuance(
                fund_code=code,
                raised_shares=values["raised_shares"],
                established_date=values["established_date"],
                source_meta=SourceMeta(
                    source="akshare_eastmoney",
                    upstream_source="eastmoney",
                    fetched_at=fetched_at,
                    quality_status=QualityStatus.PASS,
                ),
                **text_values,
            )
        )
    return rows, issues


class AkshareFundIssuanceSource(FundIssuanceSource):
    source_name = "akshare_eastmoney"

    def fetch_issuances(self) -> tuple[list[FundIssuance], list[DataQualityIssue]]:
        fetched_at = datetime.now().astimezone()
        try:
            frame = ak.fund_new_found_em()
        except Exception as exc:
            return [], [warn("fund_issuance_fetch_failed", str(exc))]
        return parse_fund_issuance_frame(frame, fetched_at=fetched_at)
