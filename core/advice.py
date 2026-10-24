"""What the review screen recommends, and why."""

from dataclasses import dataclass
from typing import Final


@dataclass(frozen=True, slots=True)
class Advice:
    """One recommendation: which option, and the code for why."""

    value: str
    reason: str


@dataclass(frozen=True, slots=True)
class FormOffer:
    """One form a campaign could be pointed at, as :func:`form_advice` needs it."""

    external_id: str
    signature: tuple[str, ...]
    leads_count: int | None


PROVIDER_EXPANDS: Final = "provider_expands"

PROVIDER_DEFAULT: Final = "provider_default"

SAME_QUESTIONS: Final = "same_questions"
NOTHING_MATCHES: Final = "nothing_matches"

SIGNAL_IS_READY: Final = "signal_is_ready"

CAMPAIGN_TYPE_REASONS: Final[dict[str, str]] = {
    "calls": "calls_cheapest",
    "leads": "form_leads_proven",
    "traffic": "site_visits_counted",
    "site_leads": "site_requests_counted",
    "views": "seen_most",
    "messages": "chat_proven",
}
PROVEN_DEFAULT: Final = "proven_default"

EVENT_ALREADY_ARRIVING: Final = "event_already_arriving"
EVENT_NOTHING_SEEN: Final = "event_nothing_seen"

BUILD_A_NEW_ONE: Final = ""


def audience_advice() -> Advice:
    """Which of the three audience modes this launch should use. Always one."""
    return Advice(value="automatic", reason=PROVIDER_EXPANDS)


def placement_advice() -> Advice:
    """Whether this ad should be allowed off Facebook and Instagram. Always."""
    return Advice(value="automatic", reason=PROVIDER_DEFAULT)


def buying_advice(*, is_offered: bool) -> Advice | None:
    """Whether to buy this campaign on the owner's own verdicts."""
    if not is_offered:
        return None
    return Advice(value="quality", reason=SIGNAL_IS_READY)


def campaign_type_advice(*, goal: str, kinds: tuple[str, ...]) -> Advice | None:
    """Which kind of campaign buys this goal, when the owner has not said."""
    if not kinds:
        return None
    return Advice(
        value=kinds[0], reason=CAMPAIGN_TYPE_REASONS.get(goal, PROVEN_DEFAULT)
    )


def conversion_event_advice(
    *, offered: tuple[str, ...], fired: tuple[str, ...], requests: frozenset[str]
) -> Advice | None:
    """Which event on the advertiser's site this campaign should be bought on."""
    if not offered:
        return None

    seen = [key for key in offered if key in fired]
    asked = [key for key in seen if key in requests]
    if asked:
        return Advice(value=asked[0], reason=EVENT_ALREADY_ARRIVING)
    if seen:
        return Advice(value=seen[0], reason=EVENT_ALREADY_ARRIVING)
    return Advice(value=offered[0], reason=EVENT_NOTHING_SEEN)


def form_advice(
    *, asked: tuple[str, ...], offers: tuple[FormOffer, ...]
) -> Advice | None:
    """The form that already asks exactly this, or the advice to build one."""
    if not offers or not asked:
        return None

    matches = [offer for offer in offers if offer.signature == asked]
    if not matches:
        return Advice(value=BUILD_A_NEW_ONE, reason=NOTHING_MATCHES)

    best = max(matches, key=lambda offer: offer.leads_count or 0)
    return Advice(value=best.external_id, reason=SAME_QUESTIONS)


__all__ = [
    "BUILD_A_NEW_ONE",
    "CAMPAIGN_TYPE_REASONS",
    "NOTHING_MATCHES",
    "PROVEN_DEFAULT",
    "PROVIDER_DEFAULT",
    "PROVIDER_EXPANDS",
    "SAME_QUESTIONS",
    "Advice",
    "FormOffer",
    "audience_advice",
    "campaign_type_advice",
    "conversion_event_advice",
    "form_advice",
    "placement_advice",
]
