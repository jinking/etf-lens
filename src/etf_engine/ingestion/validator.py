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
    if share.shares < 0:
        return [error("shares_non_negative", "shares < 0")]
    return []
