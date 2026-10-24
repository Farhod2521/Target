"""The figure a change was graded on, before the change and after it."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final, Literal

from core.agent.facts import ctr_bp
from core.agent.promises import EXPECTATIONS, as_int, rate

Measure = Literal["daily_spend", "link_ctr", "cost_per_lead", "cost_per_result"]


@dataclass(frozen=True, slots=True)
class Change:
    """One figure, before the change and after it."""

    measure: Measure
    before: int | None
    after: int | None
    days_before: int | None
    days_after: int | None
    outcome: str = ""


_MEASURES: Final[dict[str, Measure]] = {
    "spend_stops": "daily_spend",
    "delivery_resumes": "daily_spend",
    "group_delivery_resumes": "daily_spend",
    "more_delivery": "daily_spend",
    "attention_recovers": "link_ctr",
    "group_attention_recovers": "link_ctr",
    "cheaper_leads": "cost_per_lead",
    "cheaper_reported_leads": "cost_per_lead",
    "cheaper_group_leads": "cost_per_lead",
    "cheaper_results": "cost_per_result",
    "group_cheaper_results": "cost_per_result",
}

_EARLIER: Final[dict[str, str]] = {
    "cheaper_results": "attention_recovers",
    "group_cheaper_results": "group_attention_recovers",
}

_CTR_KEYS: Final[dict[str, str]] = {
    "attention_recovers": "late_ctr_bp",
    "group_attention_recovers": "link_ctr_bp",
}

_PRICE_KEYS: Final[dict[str, tuple[str, str]]] = {
    "cheaper_reported_leads": ("spend_minor", "leads_reported"),
    "cheaper_group_leads": ("adset_spend_minor", "adset_leads_reported"),
}


def before_after(
    *, rule: str, evidence: Mapping[str, Any], after: Mapping[str, Any]
) -> Change | None:
    """The one comparison this rule's verdict rests on, or nothing."""
    promise = EXPECTATIONS.get(rule, "")
    if promise in _EARLIER and "cost_minor" not in evidence:
        promise = _EARLIER[promise]
    measure = _MEASURES.get(promise)
    if measure is None or as_int(after.get("spend_minor")) is None:
        return None

    if measure == "cost_per_result":
        before = as_int(evidence.get("cost_minor"))
        later = as_int(after.get("cost_minor"))
    elif measure == "daily_spend":
        before = _per_day(evidence.get("spend_minor"), evidence.get("days"))
        later = _per_day(after.get("spend_minor"), after.get("days"))
    elif measure == "link_ctr":
        before = as_int(evidence.get(_CTR_KEYS[promise]))
        later = ctr_bp(
            clicks=as_int(after.get("link_clicks")) or 0,
            impressions=as_int(after.get("impressions")) or 0,
        )
    elif promise == "cheaper_leads":
        before = as_int(evidence.get("cpl_minor"))
        later = as_int(after.get("cpl_minor"))
    else:
        spend_key, leads_key = _PRICE_KEYS[promise]
        before = _rounded(rate(evidence.get(spend_key), evidence.get(leads_key)))
        later = _rounded(rate(after.get("spend_minor"), after.get("leads_reported")))

    if before is None:
        return None
    return Change(
        measure=measure,
        before=before,
        after=later,
        days_before=as_int(evidence.get("days")),
        days_after=as_int(after.get("days")),
        outcome=str(evidence.get("outcome") or "")
        if measure == "cost_per_result"
        else "",
    )


def _per_day(total: Any, days: Any) -> int | None:
    """Spend per day. Nought spent is nought a day, however many days."""
    amount = as_int(total)
    if amount == 0:
        return 0
    return _rounded(rate(amount, days))


def _rounded(value: float | None) -> int | None:
    return None if value is None else round(value)


__all__ = ["Change", "Measure", "before_after"]
