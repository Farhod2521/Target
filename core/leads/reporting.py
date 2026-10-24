"""Which verdicts go back to the provider, and when."""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final

from adskit import LeadStage

SETTLE_MINUTES: Final = 30


@dataclass(frozen=True, slots=True)
class Verdict:
    """One judgement, as the rules below need it."""

    lead_external_id: str
    status: str
    decided_at: datetime
    value_minor: int | None = None
    currency: str = ""


STAGE_OF: Final[dict[str, LeadStage]] = {
    "qualified": "qualified",
    "unqualified": "unqualified",
    "converted": "converted",
}


def stage_of(status: str) -> LeadStage | None:
    """The stage this verdict reports as, or nothing at all."""
    return STAGE_OF.get(status.strip().casefold())


def event_key(*, provider: str, lead_external_id: str, stage: str) -> str:
    """The idempotency key one verdict is sent under."""
    return f"{provider}:{lead_external_id}:{stage}"


def is_settled(*, decided_at: datetime, now: datetime, minutes: int) -> bool:
    """Whether this verdict has stood long enough to be worth sending."""
    return now - decided_at >= timedelta(minutes=minutes)


def is_reportable(*, decided_at: datetime, now: datetime, window_days: int) -> bool:
    """Whether the provider would still count an event stamped this far back."""
    return now - decided_at <= timedelta(days=window_days)


def due(
    *,
    verdicts: Iterable[Verdict],
    now: datetime,
    window_days: int,
    settle_minutes: int = SETTLE_MINUTES,
) -> tuple[tuple[Verdict, LeadStage], ...]:
    """The verdicts to send now, each with the stage it goes out as."""
    ready: list[tuple[Verdict, LeadStage]] = []
    for verdict in verdicts:
        stage = stage_of(verdict.status)
        if stage is None:
            continue
        if not is_settled(
            decided_at=verdict.decided_at, now=now, minutes=settle_minutes
        ):
            continue
        if not is_reportable(
            decided_at=verdict.decided_at, now=now, window_days=window_days
        ):
            continue
        ready.append((verdict, stage))
    return tuple(ready)


def expired(
    *, verdicts: Iterable[Verdict], now: datetime, window_days: int
) -> tuple[Verdict, ...]:
    """The ones the provider will never count, however often they are sent."""
    return tuple(
        verdict
        for verdict in verdicts
        if not is_reportable(
            decided_at=verdict.decided_at, now=now, window_days=window_days
        )
    )


__all__ = [
    "SETTLE_MINUTES",
    "STAGE_OF",
    "Verdict",
    "due",
    "event_key",
    "expired",
    "is_reportable",
    "is_settled",
    "stage_of",
]
