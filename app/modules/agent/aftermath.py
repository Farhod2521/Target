from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

from app.common.money import format_minor
from app.modules.agent.figures import bp_percent
from core.agent.before_after import Change, Measure, before_after

_LABELS: Final[dict[Measure, Any]] = {
    "daily_spend": "Kunlik sarf",
    "link_ctr": "Bosish ulushi",
    "cost_per_lead": "Bitta murojaat narxi",
}
_NOTHING: Final[dict[Measure, Any]] = {
    "daily_spend": "—",
    "link_ctr": "ko'rsatilmadi",
    "cost_per_lead": "murojaat yo'q",
}


@dataclass(frozen=True, slots=True)
class Comparison:
    label: Any
    before: str
    after: str
    period: str


def comparison(
    *, rule: str, evidence: Mapping[str, Any], after: Mapping[str, Any], currency: str
) -> Comparison | None:
    change = before_after(rule=rule, evidence=evidence, after=after)
    if change is None:
        return None
    return Comparison(
        label=_LABELS[change.measure],
        before=_figure(change.measure, change.before, currency),
        after=_figure(change.measure, change.after, currency),
        period=_period(change),
    )


def _figure(measure: Measure, value: int | None, currency: str) -> str:
    if value is None:
        return str(_NOTHING[measure])
    if measure == "link_ctr":
        return bp_percent(value)
    return format_minor(amount_minor=value, currency=currency)


def _period(change: Change) -> str:
    if not change.days_before or not change.days_after:
        return ""
    return (
        "Tasdiqlangandan keyingi %(after)d kun, undan oldingi %(before)d kun bilan solishtirildi."
        % {"after": change.days_after, "before": change.days_before}
    )


__all__ = ["Comparison", "comparison"]
