"""宽基指数估值序列（乐咕口径，月度）。

上游按加权 / 等权两种口径提供静态与滚动市盈率，本适配器**原样落库**，
不挑一个当"官方值"，也不做口径换算。没有序列的指数（创业板指、科创50）
如实记 issue。
"""

import time
from datetime import datetime
from decimal import Decimal, InvalidOperation

import akshare as ak
import pandas as pd

from etf_engine.domain.enums import QualityStatus
from etf_engine.domain.models import IndexValuation, SourceMeta
from etf_engine.domain.quality import DataQualityIssue, warn
from etf_engine.sources.base import IndexValuationSource

METRIC_BASIS = "lg_index_pe_monthly"

#: 上游的 symbol 参数（它不是指数代码，是名称枚举）。
LEGU_SYMBOLS: dict[str, str] = {
    "000016": "上证50",
    "000300": "沪深300",
    "000905": "中证500",
    "000852": "中证1000",
}

#: 上游中文字段 → 库内字段。
_COLUMNS = {
    "静态市盈率": "pe_static",
    "滚动市盈率": "pe_ttm",
    "静态市盈率中位数": "pe_static_median",
    "滚动市盈率中位数": "pe_ttm_median",
    "等权静态市盈率": "pe_static_equal_weight",
    "等权滚动市盈率": "pe_ttm_equal_weight",
}


def _decimal(value) -> Decimal | None:
    if value is None or pd.isna(value):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def parse_index_valuation_frame(
    frame: pd.DataFrame,
    *,
    index_id: str,
    fetched_at: datetime,
) -> tuple[list[IndexValuation], list[DataQualityIssue]]:
    if frame is None or frame.empty:
        return [], [warn("index_valuation_empty", f"{index_id} 估值序列为空")]
    if "日期" not in frame.columns:
        raise RuntimeError("指数估值序列缺少 日期 列")

    rows: list[IndexValuation] = []
    issues: list[DataQualityIssue] = []
    for _, row in frame.iterrows():
        try:
            trade_date = pd.Timestamp(row["日期"]).date()
        except (ValueError, TypeError):
            issues.append(warn("index_valuation_date_invalid", f"{index_id} {row['日期']!r}"))
            continue
        values = {target: _decimal(row.get(source)) for source, target in _COLUMNS.items()}
        if values["pe_ttm"] is None and values["pe_static"] is None:
            # 滚动 PE 是分位计算的主字段：它缺失的行不入库。
            issues.append(
                warn("index_valuation_pe_missing", f"{index_id} {trade_date} 市盈率为空")
            )
            continue
        rows.append(
            IndexValuation(
                index_id=index_id,
                trade_date=trade_date,
                metric_basis=METRIC_BASIS,
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


class AkshareIndexValuationSource(IndexValuationSource):
    source_name = "akshare_legu"

    def fetch_index_valuations(
        self,
        index_ids: list[str],
        *,
        attempts: int = 4,
        sleep_seconds: float = 0.4,
    ) -> tuple[list[IndexValuation], list[DataQualityIssue]]:
        """逐个指数取估值序列。

        上游对部分指数（中证500 / 中证1000）会间歇性抛异常，所以做**逐指数**
        有界重试：一个指数失败不影响其它指数，重试仍失败才记 issue，
        绝不用别的指数顶替。
        """
        fetched_at = datetime.now().astimezone()
        rows: list[IndexValuation] = []
        issues: list[DataQualityIssue] = []

        for position, index_id in enumerate(index_ids):
            if position:
                time.sleep(sleep_seconds)
            symbol = LEGU_SYMBOLS.get(index_id)
            if symbol is None:
                issues.append(
                    warn(
                        "index_valuation_symbol_missing",
                        f"{index_id} 在上游没有估值序列（可能只有价格与成分数据）",
                    )
                )
                continue

            frame = None
            last_error: Exception | None = None
            for attempt in range(attempts):
                if attempt:
                    time.sleep(sleep_seconds * (2**attempt))
                try:
                    frame = ak.stock_index_pe_lg(symbol=symbol)
                    break
                except Exception as exc:  # noqa: BLE001 - 上游异常类型不稳定
                    last_error = exc
            if frame is None:
                issues.append(
                    warn(
                        "index_valuation_fetch_failed",
                        f"{index_id}（{symbol}）重试 {attempts} 次仍失败：{last_error}",
                    )
                )
                continue
            try:
                parsed, parse_issues = parse_index_valuation_frame(
                    frame, index_id=index_id, fetched_at=fetched_at
                )
            except RuntimeError as exc:
                issues.append(warn("index_valuation_schema_changed", f"{index_id}: {exc}"))
                continue
            rows.extend(parsed)
            issues.extend(parse_issues)

        return rows, issues
