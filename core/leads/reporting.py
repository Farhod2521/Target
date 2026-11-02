"""What a card says about a lead, and when it may go back to the provider."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final

from adskit import LeadStage

STAGE_ORDER: Final[tuple[LeadStage, ...]] = (
    "received",
    "qualified",
    "unqualified",
    "converted",
)
# Sent at night, so a day's margin on the window is not needed; an hour keeps
# an event at the very edge from being refused and taking its batch with it.
WINDOW_MARGIN: Final = timedelta(hours=1)
# The provider discards an event stamped before the lead it names.
AFTER_THE_LEAD: Final = timedelta(seconds=1)


@dataclass(frozen=True, slots=True)
class CardFacts:
    """A card as the rules below need it."""

    kind: str
    submitted_at: datetime
    placed_at: datetime
    qualified_at: datetime | None = None
    closed_at: datetime | None = None
    value_minor: int | None = None
    currency: str = ""


@dataclass(frozen=True, slots=True)
class Signal:
    """One stage of one lead, as it would be told."""

    stage: LeadStage
    occurred_at: datetime
    value_minor: int | None = None
    currency: str = ""


def card_signals(card: CardFacts) -> tuple[Signal, ...]:
    """Every stage this card stands at now, earliest first.

    Asked of the card as it stands at night, so a mistake put right the same
    day says nothing. A card lost or put back in «Yangi lid» keeps only that
    it arrived: a qualification it no longer stands by is not told.
    """
    found = [Signal("received", _after_lead(card, card.placed_at))]
    closed = card.closed_at
    if card.kind == "junk" and closed is not None:
        found.append(Signal("unqualified", _after_lead(card, closed)))
        return tuple(found)
    if card.kind == "won" and closed is not None:
        found.append(
            Signal("qualified", _after_lead(card, card.qualified_at or closed))
        )
        found.append(
            Signal(
                "converted",
                _after_lead(card, closed),
                value_minor=card.value_minor,
                currency=card.currency,
            )
        )
        return tuple(found)
    if card.qualified_at is not None and card.kind == "open":
        found.append(Signal("qualified", _after_lead(card, card.qualified_at)))
    return tuple(found)


def _after_lead(card: CardFacts, at: datetime) -> datetime:
    return max(at, card.submitted_at + AFTER_THE_LEAD)


def event_key(*, provider: str, lead_external_id: str, stage: str) -> str:
    """The idempotency key one stage is sent under."""
    return f"{provider}:{lead_external_id}:{stage}"


def is_reportable(*, occurred_at: datetime, now: datetime, window_days: int) -> bool:
    """Whether the provider would still take an event stamped this far back."""
    return now - occurred_at <= timedelta(days=window_days) - WINDOW_MARGIN


def stage_rank(stage: str) -> int:
    """Where a stage falls in a lead's journey: earlier ones are told first."""
    return STAGE_ORDER.index(stage)


__all__ = [
    "AFTER_THE_LEAD",
    "STAGE_ORDER",
    "WINDOW_MARGIN",
    "CardFacts",
    "Signal",
    "card_signals",
    "event_key",
    "is_reportable",
    "stage_rank",
]
