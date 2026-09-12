"""市场活跃度：涨跌家数、涨跌停家数、活跃度。

上游返回的是 ``item / value`` 两列的窄表，且**自带统计日期**——
不能拿本地运行日当交易日（运行日可能是周末），拿不到统计日期就不入库。
"""

from datetime import date, datetime
from decimal import Decimal, InvalidOperation

import akshare as ak
import pandas as pd

from etf_engine.domain.enums import QualityStatus
from etf_engine.domain.models import MarketActivity, SourceMeta
from etf_engine.domain.quality import DataQualityIssue, warn
from etf_engine.sources.base import MarketActivitySource

#: 上游中文标签 → 库内字段。
_ITEM_FIELDS = {
    "上涨": "rising_count",
    "下跌": "falling_count",
    "平盘": "flat_count",
    "停牌": "suspended_count",
    "涨停": "limit_up_count",
    "跌停": "limit_down_count",
    "真实涨停": "real_limit_up_count",
    "真实跌停": "real_limit_down_count",
}

#: 带百分号的字段，单独处理。
_PERCENT_FIELDS = {"活跃度": "activity_pct"}


def _decimal(value) -> Decimal | None:
    if value is None or pd.isna(value):
        return None
    text = str(value).strip().replace("%", "")
    if not text:
        return None
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return None


def parse_activity_frame(
    frame: pd.DataFrame,
    *,
    fetched_at: datetime,
    trade_date: date | None = None,
) -> tuple[list[MarketActivity], list[DataQualityIssue]]:
    if frame is None or frame.empty:
        return [], [warn("activity_empty", "市场活跃度空结果")]
    for column in ("item", "value"):
        if column not in frame.columns:
            raise RuntimeError(f"市场活跃度缺少 {column} 列")

    items = {str(row["item"]).strip(): row["value"] for _, row in frame.iterrows()}
    issues: list[DataQualityIssue] = []

    statistic_at = None
    if "统计日期" in items and not pd.isna(items["统计日期"]):
        statistic_at = pd.Timestamp(items["统计日期"]).to_pydatetime()

    resolved_date = trade_date
    if resolved_date is None and statistic_at is not None:
        resolved_date = statistic_at.date()
    if resolved_date is None:
        # 拿不到统计日期就不入库：运行日不等于交易日。
        return [], [warn("activity_date_missing", "市场活跃度既无统计日期也未传入交易日")]

    values: dict[str, Decimal | None] = {}
    for label, field in {**_ITEM_FIELDS, **_PERCENT_FIELDS}.items():
        if label not in items:
            issues.append(warn("activity_item_missing", f"市场活跃度缺少 {label}"))
            continue
        values[field] = _decimal(items[label])

    return (
        [
            MarketActivity(
                trade_date=resolved_date,
                statistic_at=statistic_at,
                source_meta=SourceMeta(
                    source="akshare_legu",
                    upstream_source="legu",
                    fetched_at=fetched_at,
                    quality_status=QualityStatus.PASS,
                ),
                **values,
            )
        ],
        issues,
    )


class AkshareMarketActivitySource(MarketActivitySource):
    source_name = "akshare_legu"

    def fetch_activity(
        self, trade_date: date | None = None
    ) -> tuple[list[MarketActivity], list[DataQualityIssue]]:
        fetched_at = datetime.now().astimezone()
        try:
            frame = ak.stock_market_activity_legu()
        except Exception as exc:
            return [], [warn("activity_fetch_failed", str(exc))]
        return parse_activity_frame(frame, fetched_at=fetched_at, trade_date=trade_date)
