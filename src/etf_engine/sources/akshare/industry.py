"""个股行业分类适配器（上游事实来源：巨潮资讯 cninfo）。

历史实现把行业分类写死在 ``services/tagging_service.py`` 的一张 80 行字典里：
既不是数据源事实，也没有口径版本。这里改为从数据源逐只股票取行业分类，
并把分类标准一起落库。
"""

from datetime import date, datetime

import akshare as ak
import pandas as pd

from etf_engine.domain.enums import QualityStatus
from etf_engine.domain.identifiers import SecurityId
from etf_engine.domain.models import SourceMeta, StockIndustry
from etf_engine.domain.quality import DataQualityIssue, warn

#: 优先使用的分类标准，按顺序取第一个命中的。
STANDARD_PREFERENCE = ("中证行业分类标准", "中国上市公司协会上市公司行业分类标准")

#: 行业名称的取值优先级：大类 > 次类 > 门类。
INDUSTRY_FIELDS = ("行业大类", "行业次类", "行业门类")

#: cninfo 是 A 股登记/分类口径，不覆盖港股。
SUPPORTED_EXCHANGES = ("SSE", "SZSE", "BJSE")

#: 解析所需的列，缺列说明返回体形状变了，必须报出来而不是猜。
REQUIRED_COLUMNS = ("证券代码", "分类标准", "变更日期")


def parse_industry_frames(
    frames: list[pd.DataFrame],
    *,
    fetched_at: datetime,
) -> tuple[list[StockIndustry], list[DataQualityIssue]]:
    """把每只股票的行业变更表解析成当前分类。

    一只股票可能同时出现在多套分类标准下；按 ``STANDARD_PREFERENCE`` 取一套，
    再取其中最新变更日期的一行。取不到就留问题，不猜。
    """
    industries: list[StockIndustry] = []
    seen: set[str] = set()
    issues: list[DataQualityIssue] = []

    for frame in frames:
        if frame is None or frame.empty:
            continue
        missing = [column for column in REQUIRED_COLUMNS if column not in frame.columns]
        if missing:
            issues.append(warn("industry_frame_shape_changed", f"缺少列 {missing}"))
            continue

        latest = frame.copy()
        latest["_changed"] = pd.to_datetime(latest.get("变更日期"), errors="coerce")
        for standard in STANDARD_PREFERENCE:
            matched = latest[latest.get("分类标准") == standard]
            if matched.empty:
                continue
            row = matched.sort_values("_changed", na_position="first").iloc[-1]
            industry_name = next(
                (str(row.get(field)) for field in INDUSTRY_FIELDS if pd.notna(row.get(field))),
                None,
            )
            raw_code = str(row.get("证券代码", "")).strip()
            if industry_name is None:
                issues.append(warn("industry_name_missing", f"{raw_code} 分类标准={standard}"))
                break
            try:
                stock_id = SecurityId.parse(raw_code).value
            except ValueError:
                issues.append(warn("industry_code_unresolved", f"证券代码={raw_code!r}"))
                break
            if stock_id in seen:
                break
            seen.add(stock_id)
            industries.append(
                StockIndustry(
                    stock_id=stock_id,
                    stock_name=str(row.get("新证券简称", "")).strip() or None,
                    industry_name=industry_name,
                    industry_code=str(row.get("行业编码", "")).strip() or None,
                    classification_standard=standard,
                    source_meta=SourceMeta(
                        source="cninfo",
                        upstream_source="cninfo",
                        fetched_at=fetched_at,
                        quality_status=QualityStatus.PASS,
                    ),
                )
            )
            break
        else:
            raw_code = str(frame["证券代码"].iloc[0]).strip()
            issues.append(
                warn(
                    "industry_standard_unavailable",
                    f"{raw_code} 没有命中 {STANDARD_PREFERENCE} 中的任何分类标准",
                )
            )

    return industries, issues


class AkshareStockIndustrySource:
    """按证券逐只取行业分类（cninfo 行业变更接口）。"""

    source_name = "cninfo"

    def fetch_industries(
        self, security_ids: list[str]
    ) -> tuple[list[StockIndustry], list[DataQualityIssue]]:
        fetched_at = datetime.now().astimezone()
        frames: list[pd.DataFrame] = []
        issues: list[DataQualityIssue] = []

        for security_id in security_ids:
            sid = SecurityId.parse(security_id)
            if sid.exchange.value not in SUPPORTED_EXCHANGES:
                # 港股/海外标的没有 A 股行业分类，如实标注来源不适用。
                issues.append(
                    warn(
                        "industry_source_not_applicable",
                        f"{sid.value} 不在 cninfo（A 股）分类口径内",
                    )
                )
                continue
            try:
                frame = ak.stock_industry_change_cninfo(
                    symbol=sid.ticker,
                    start_date="20000101",
                    end_date=date.today().strftime("%Y%m%d"),
                )
            except Exception as exc:
                issues.append(warn("industry_fetch_failed", f"{sid.value}: {exc}"))
                continue
            if frame is None or frame.empty:
                issues.append(warn("industry_not_disclosed", sid.value))
                continue
            frames.append(frame)

        industries, parse_issues = parse_industry_frames(frames, fetched_at=fetched_at)
        return industries, [*issues, *parse_issues]
