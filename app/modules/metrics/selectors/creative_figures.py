from decimal import Decimal
from typing import Any

from app.common.dates import number_format
from app.common.money import format_minor
from app.modules.metrics.selectors.creative_leads import CreativeLeads
from core.metrics import cost_per, rate_bp


def rate(*, part: int, whole: int) -> str:
    if whole <= 0:
        return ""
    share = Decimal(rate_bp(part=part, whole=whole)) / 100
    return f"{number_format(share, decimal_pos=1)}%"


def cpql(*, spend_minor: int, own: CreativeLeads, currency: str) -> str:
    if not own.is_judged:
        return ""
    return format_minor(
        amount_minor=cost_per(spend_minor, own.qualified), currency=currency
    )


def verdict(index: int | None) -> Any:
    if index is None:
        return ""
    if index == 100:
        return "o'rtacha"
    if index < 100:
        return "o'rtachadan %(pct)s%% arzon" % {"pct": 100 - index}
    return "o'rtachadan %(pct)s%% qimmat" % {"pct": index - 100}


__all__ = ["cpql", "rate", "verdict"]
