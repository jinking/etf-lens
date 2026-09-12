from etf_engine.domain.models import ETFQuote, ETFShare
from etf_engine.domain.quality import DataQualityIssue, error


def validate_quote(quote: ETFQuote) -> list[DataQualityIssue]:
    issues: list[DataQualityIssue] = []

    if quote.high is not None:
        for field_name, value in (("open", quote.open), ("close", quote.close)):
            if value is not None and quote.high < value:
                issues.append(error("high_gte_prices", f"high < {field_name}"))

    if quote.low is not None:
        for field_name, value in (("open", quote.open), ("close", quote.close)):
            if value is not None and quote.low > value:
                issues.append(error("low_lte_prices", f"low > {field_name}"))

    for field_name, value in (
        ("volume", quote.volume),
        ("turnover_amount", quote.turnover_amount),
    ):
        if value is not None and value < 0:
            issues.append(error(f"{field_name}_non_negative", f"{field_name} < 0"))

    return issues


def validate_share(share: ETFShare) -> list[DataQualityIssue]:
    """份额必须是正数。

    ``shares <= 0`` 一律拦下：0 份不可能是一个存续 ETF 的事实，
    它要么是上游"该日无数据"的占位、要么是解析问题。放进库里会立刻变成
    一笔假的巨额赎回（实测 560650.SH 在 2026-08-21 起被写成 0，派生出一条
    ``share_change_1d = -7,919,200`` 的申赎记录）。

    按项目纪律：拒绝写入 + 记 ``ops.quality_issue``，不静默丢弃、也不用 NULL
    顶替（份额字段本身非空，缺失就没有这条事实）。
    """
    if share.shares <= 0:
        return [
            error(
                "shares_positive",
                f"{share.security_id} {share.trade_date} shares={share.shares}"
                "（<= 0，上游占位值不能当事实）",
            )
        ]
    return []
