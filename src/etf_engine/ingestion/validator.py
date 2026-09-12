from dataclasses import dataclass

from etf_engine.domain.models import ETFQuote, ETFShare


@dataclass(slots=True)
class ValidationIssue:
    severity: str
    rule_name: str
    details: str


def validate_quote(quote: ETFQuote) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []

    if quote.high is not None:
        for field_name, value in (("open", quote.open), ("close", quote.close)):
            if value is not None and quote.high < value:
                issues.append(
                    ValidationIssue(
                        severity="ERROR",
                        rule_name="high_gte_prices",
                        details=f"high < {field_name}",
                    )
                )

    if quote.low is not None:
        for field_name, value in (("open", quote.open), ("close", quote.close)):
            if value is not None and quote.low > value:
                issues.append(
                    ValidationIssue(
                        severity="ERROR",
                        rule_name="low_lte_prices",
                        details=f"low > {field_name}",
                    )
                )

    for field_name, value in (
        ("volume", quote.volume),
        ("turnover_amount", quote.turnover_amount),
    ):
        if value is not None and value < 0:
            issues.append(
                ValidationIssue(
                    severity="ERROR",
                    rule_name=f"{field_name}_non_negative",
                    details=f"{field_name} < 0",
                )
            )

    return issues


def validate_share(share: ETFShare) -> list[ValidationIssue]:
    if share.shares < 0:
        return [
            ValidationIssue(
                severity="ERROR",
                rule_name="shares_non_negative",
                details="shares < 0",
            )
        ]
    return []
