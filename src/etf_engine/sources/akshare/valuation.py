"""全 A 估值与历史分位。

上游（乐咕乐股口径）直接提供"当前 PE 在全部历史 / 近十年中的分位"，
这是**上游给出的事实**，本系统不做二次推导，也不与别的来源的分位混用；
口径标识写在 ``metric_basis``。
"""

from datetime import date, datetime
from decimal import Decimal

import akshare as ak
import pandas as pd

from etf_engine.domain.enums import QualityStatus
from etf_engine.domain.models import MarketValuation, SourceMeta
from etf_engine.domain.quality import DataQualityIssue, warn
from etf_engine.sources.base import MarketValuationSource

#: 全 A 口径在库内的 index_id（不是真实指数代码，避免与指数目录混淆）。
ALL_A_INDEX_ID = "CN_A_ALL"
ALL_A_METRIC_BASIS = "lg_stock_a_ttm_lyr"

_COLUMNS = {
    "middlePETTM": "pe_ttm_median",
    "averagePETTM": "pe_ttm_mean",
    "middlePELYR": "pe_lyr_median",
    "averagePELYR": "pe_lyr_mean",
    "close": "index_close",
    "quantileInAllHistoryMiddlePeTtm": "quantile_ttm_median_all_history",
    "quantileInRecent10YearsMiddlePeTtm": "quantile_ttm_median_10y",
    "quantileInAllHistoryMiddlePeLyr": "quantile_lyr_median_all_history",
    "quantileInRecent10YearsMiddlePeLyr": "quantile_lyr_median_10y",
}


def _decimal(value) -> Decimal | None:
    if value is None or pd.isna(value):
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def parse_valuation_frame(
    frame: pd.DataFrame,
    *,
    index_id: str = ALL_A_INDEX_ID,
    metric_basis: str = ALL_A_METRIC_BASIS,
    fetched_at: datetime,
    start_date: date | None = None,
) -> tuple[list[MarketValuation], list[DataQualityIssue]]:
    if frame is None or frame.empty:
        return [], [warn("valuation_empty", "估值数据为空")]
    if "date" not in frame.columns:
        raise RuntimeError("估值数据缺少 date 列")

    rows: list[MarketValuation] = []
    issues: list[DataQualityIssue] = []
    for _, row in frame.iterrows():
        try:
            trade_date = pd.Timestamp(row["date"]).date()
        except (ValueError, TypeError):
            issues.append(warn("valuation_date_invalid", f"date={row['date']!r}"))
            continue
        if start_date is not None and trade_date < start_date:
            continue

        values = {target: _decimal(row.get(source)) for source, target in _COLUMNS.items()}
        if all(value is None for value in values.values()):
            # 整行都是空值（上游早期行常见），如实跳过并留痕。
            issues.append(warn("valuation_row_empty", f"{index_id} {trade_date} 全为空值"))
            continue
        rows.append(
            MarketValuation(
                index_id=index_id,
                trade_date=trade_date,
                metric_basis=metric_basis,
                source_meta=SourceMeta(
                    source="akshare_legu",
                    upstream_source="legu",
                    fetched_at=fetched_at,
                    quality_status=QualityStatus.PASS,
                ),
                **values,
            )
        )
    return rows, issues


class AkshareMarketValuationSource(MarketValuationSource):
    source_name = "akshare_legu"

    def fetch_valuation(
        self, start_date: date | None = None
    ) -> tuple[list[MarketValuation], list[DataQualityIssue]]:
        fetched_at = datetime.now().astimezone()
        try:
            frame = ak.stock_a_ttm_lyr()
        except Exception as exc:
            return [], [warn("valuation_fetch_failed", str(exc))]
        return parse_valuation_frame(frame, fetched_at=fetched_at, start_date=start_date)
