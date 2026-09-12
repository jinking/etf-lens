"""指数目录、指数成分与指数行情适配器。

- 指数目录：中证指数公司全量清单（代码/全称/简称）+ 新浪指数列表（行情符号）。
- 指数成分：中证指数成分权重（含成分券与权重）。
- 指数行情：新浪指数日线（仅覆盖新浪在列的指数，其余如实标注来源缺失）。
"""

from datetime import date, datetime
from decimal import Decimal, InvalidOperation

import akshare as ak
import pandas as pd

from etf_engine.domain.enums import QualityStatus
from etf_engine.domain.identifiers import SecurityId
from etf_engine.domain.models import (
    IndexCatalogEntry,
    IndexConstituent,
    IndexQuote,
    SourceMeta,
)
from etf_engine.domain.quality import DataQualityIssue, error, warn
from etf_engine.sources.base import IndexConstituentSource


def _decimal(value) -> Decimal | None:
    if value is None or pd.isna(value):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def parse_csindex_catalog(frame: pd.DataFrame) -> list[tuple[str, str, str]]:
    """中证指数清单 → ``(代码, 全称, 简称)``。"""
    for column in ("指数代码", "指数全称", "指数简称"):
        if column not in frame.columns:
            raise RuntimeError(f"指数目录缺少 {column} 列")
    rows: list[tuple[str, str, str]] = []
    for _, row in frame.iterrows():
        code = str(row["指数代码"]).strip()
        if not code.isdigit():
            continue
        rows.append((code, str(row["指数全称"]).strip(), str(row["指数简称"]).strip()))
    return rows


def parse_sina_symbols(frame: pd.DataFrame) -> dict[str, str]:
    """新浪指数列表 → ``{6 位代码: 行情符号}``（如 ``sh000300``）。"""
    if "代码" not in frame.columns:
        raise RuntimeError("新浪指数列表缺少 代码 列")
    symbols: dict[str, str] = {}
    for _, row in frame.iterrows():
        symbol = str(row["代码"]).strip().lower()
        if len(symbol) != 8 or not symbol[2:].isdigit():
            continue
        symbols.setdefault(symbol[2:], symbol)
    return symbols


def parse_constituent_frame(
    frame: pd.DataFrame,
    *,
    index_id: str,
    fetched_at: datetime,
) -> tuple[list[IndexConstituent], list[DataQualityIssue]]:
    constituents: list[IndexConstituent] = []
    issues: list[DataQualityIssue] = []

    for column in ("日期", "成分券代码", "成分券名称"):
        if column not in frame.columns:
            raise RuntimeError(f"指数成分缺少 {column} 列")

    for _, row in frame.iterrows():
        raw_code = str(row["成分券代码"]).strip()
        try:
            effective_date = pd.Timestamp(row["日期"]).date()
        except (ValueError, TypeError):
            issues.append(warn("constituent_date_invalid", f"{index_id} 日期={row['日期']!r}"))
            continue
        try:
            stock_id = SecurityId.parse(raw_code).value
        except ValueError:
            # 港股通等非 A 股成分不在本系统标识符范围内，如实记录并跳过。
            issues.append(
                warn(
                    "constituent_code_out_of_scope",
                    f"{index_id} 成分券代码={raw_code!r} 名称={row['成分券名称']!r}",
                )
            )
            continue

        constituents.append(
            IndexConstituent(
                index_id=index_id,
                effective_date=effective_date,
                stock_id=stock_id,
                stock_name=str(row["成分券名称"]).strip() or None,
                weight_pct=_decimal(row.get("权重")),
                source_meta=SourceMeta(
                    source="csindex",
                    upstream_source="csindex",
                    fetched_at=fetched_at,
                    quality_status=QualityStatus.PASS,
                ),
            )
        )

    return constituents, issues


def parse_index_quote_frame(
    frame: pd.DataFrame,
    *,
    index_id: str,
    fetched_at: datetime,
    start_date: date | None = None,
    end_date: date | None = None,
) -> list[IndexQuote]:
    if frame is None or frame.empty or "date" not in frame.columns:
        raise RuntimeError("指数行情返回体缺少 date 列（该指数可能不在数据源覆盖范围内）")

    quotes: list[IndexQuote] = []
    for _, row in frame.iterrows():
        trade_date = pd.Timestamp(row["date"]).date()
        if start_date is not None and trade_date < start_date:
            continue
        if end_date is not None and trade_date > end_date:
            continue
        close = _decimal(row.get("close"))
        if close is None:
            continue
        quotes.append(
            IndexQuote(
                index_id=index_id,
                trade_date=trade_date,
                open=_decimal(row.get("open")),
                high=_decimal(row.get("high")),
                low=_decimal(row.get("low")),
                close=close,
                currency="CNY",
                source_meta=SourceMeta(
                    source="sina",
                    upstream_source="sina",
                    fetched_at=fetched_at,
                    quality_status=QualityStatus.PASS,
                ),
            )
        )
    return quotes


class AkshareIndexCatalogSource:
    """指数目录：中证全量清单 + 新浪行情符号。"""

    def fetch_catalog(self) -> tuple[list[IndexCatalogEntry], list[DataQualityIssue]]:
        fetched_at = datetime.now().astimezone()
        issues: list[DataQualityIssue] = []

        catalog_rows = parse_csindex_catalog(ak.index_csindex_all())
        try:
            symbols = parse_sina_symbols(ak.stock_zh_index_spot_sina())
        except Exception as exc:
            symbols = {}
            issues.append(warn("index_symbols_unavailable", str(exc)))

        entries = [
            IndexCatalogEntry(
                index_id=code,
                index_name=full_name or short_name,
                market_symbol=symbols.get(code),
                source_meta=SourceMeta(
                    source="csindex",
                    upstream_source="csindex",
                    fetched_at=fetched_at,
                    quality_status=QualityStatus.PASS,
                ),
            )
            for code, full_name, short_name in catalog_rows
        ]
        return entries, issues


class AkshareIndexConstituentSource(IndexConstituentSource):
    """中证指数成分权重。"""

    def fetch_constituents(
        self, index_id: str, effective_date: date | None = None
    ) -> list[IndexConstituent]:
        constituents, _ = self.fetch_constituents_with_issues(index_id)
        return constituents

    #: 非中证系列（如交易所自编指数）没有该接口。
    def fetch_constituents_with_issues(
        self, index_id: str
    ) -> tuple[list[IndexConstituent], list[DataQualityIssue]]:
        fetched_at = datetime.now().astimezone()
        try:
            frame = ak.index_stock_cons_weight_csindex(symbol=index_id)
        except Exception as exc:
            return [], [warn("constituent_source_unavailable", f"{index_id}: {exc}")]
        if frame is None or frame.empty:
            return [], [warn("constituent_source_unavailable", f"{index_id}: 空结果")]
        return parse_constituent_frame(frame, index_id=index_id, fetched_at=fetched_at)


class AkshareIndexQuoteSource:
    """新浪指数日线（仅有行情符号的指数）。"""

    def fetch_quotes(
        self, index_id: str, market_symbol: str, start_date: date, end_date: date
    ) -> tuple[list[IndexQuote], list[DataQualityIssue]]:
        fetched_at = datetime.now().astimezone()
        try:
            frame = ak.stock_zh_index_daily(symbol=market_symbol)
        except Exception as exc:
            return [], [warn("index_quote_failed", f"{index_id} ({market_symbol}): {exc}")]
        try:
            quotes = parse_index_quote_frame(
                frame,
                index_id=index_id,
                fetched_at=fetched_at,
                start_date=start_date,
                end_date=end_date,
            )
        except RuntimeError as exc:
            return [], [warn("index_quote_unavailable", f"{index_id} ({market_symbol}): {exc}")]
        if not quotes:
            return [], [warn("index_quote_empty", f"{index_id} ({market_symbol})")]
        return quotes, []


def missing_quote_source_issue(index_id: str) -> DataQualityIssue:
    return error(
        "index_quote_source_missing",
        f"{index_id} 在目录里没有行情符号（新浪未收录该指数），指数行情留空",
    )


class AkshareETFBenchmarkSource:
    """按基金取"业绩比较基准"文本（同花顺基金概况）。"""

    def fetch_benchmark(self, security_id: str) -> str | None:
        sid = SecurityId.parse(security_id)
        frame = ak.fund_info_ths(symbol=sid.ticker)
        return parse_benchmark_frame(frame)


def parse_benchmark_frame(frame: pd.DataFrame) -> str | None:
    """从"字段/值"两列的基金概况里取出业绩比较基准。"""
    if frame is None or frame.empty:
        return None
    for column in ("字段", "值"):
        if column not in frame.columns:
            raise RuntimeError("基金概况返回体缺少 字段/值 列")
    matched = frame[frame["字段"].astype(str).str.contains("业绩比较基准", na=False)]
    if matched.empty:
        return None
    value = str(matched.iloc[0]["值"]).strip()
    return value or None
