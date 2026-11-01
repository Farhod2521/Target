"""What has happened that this account has not been told about yet.

One shape for every read: ask what is true now, ask what has already been
announced, and return the difference. "Already announced" is not "a journal
row exists" - rows are written before the message goes out - but "it
arrived, or was tried as often as this product is willing to"; see
:func:`settled`. Anything between is an attempt still owed and the next
sweep offers it again.

The ``owners_with_*`` reads are the sweep's first question, and deliberately
wider than the truth: a filter so the quarter-hourly pass skips the accounts
with nothing, never the decision of what is owed.
"""

from datetime import datetime, timedelta
from typing import Final
from uuid import UUID

from sqlalchemy import ColumnElement, cast, or_, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Session, joinedload

from app.modules.accounts.models import User
from app.modules.ads.constants import ManagedLevel
from app.modules.ads.models import Ad, AdSet, Campaign
from app.modules.ads.selectors import PageScope, all_launched_campaign_ids
from app.modules.agent.constants import SuggestionOutcome, SuggestionStatus
from app.modules.agent.models import AgentSuggestion
from app.modules.agent.selectors.suggestions import recently_assessed, waiting
from app.modules.notifications.constants import (
    MAX_REJECTIONS_PER_SWEEP,
    NOTICE_TRIES,
    OUTCOME_NOTICE_HOURS,
    NoticeKind,
)
from app.modules.notifications.keys import outcome_subject, rejection_subject
from app.modules.notifications.models import TelegramNotice

# "Unclear" stays in the cabinet: a phone buzzing to say the product could
# not tell is a phone taught to ignore the next one. "Gone" is about the
# object, not the change.
NEWS_OUTCOMES: Final = (SuggestionOutcome.WORKED, SuggestionOutcome.NOT_WORKED)


def settled() -> ColumnElement[bool]:
    """The claims no sweep picks up again: delivered, or given up on."""
    return or_(
        TelegramNotice.sent_at.is_not(None), TelegramNotice.attempts >= NOTICE_TRIES
    )


def announced(db: Session, *, owner: User, kind: str) -> set[str]:
    """Every subject of this kind that will not be sent again."""
    return set(
        db.scalars(
            select(TelegramNotice.subject).where(
                TelegramNotice.owner_id == owner.id,
                TelegramNotice.kind == str(kind),
                settled(),
            )
        )
    )


def unannounced_suggestions(
    db: Session, *, owner: User, now: datetime
) -> list[AgentSuggestion]:
    """Open proposals nobody has been told about, on the agent's own ``waiting``
    so the phone and the cabinet never disagree about what is open."""
    seen = announced(db, owner=owner, kind=NoticeKind.SUGGESTION)
    return [row for row in waiting(db, owner=owner, now=now) if str(row.id) not in seen]


def unannounced_outcomes(
    db: Session, *, owner: User, now: datetime
) -> list[AgentSuggestion]:
    """Verdicts from the last day nobody has been told about, newest first."""
    seen = announced(db, owner=owner, kind=NoticeKind.SUGGESTION)
    fresh = recently_assessed(
        db, owner=owner, since=now - timedelta(hours=OUTCOME_NOTICE_HOURS), limit=None
    )
    return [
        row
        for row in fresh
        if row.outcome in NEWS_OUTCOMES and outcome_subject(pk=row.id) not in seen
    ]


def rejected_ads(db: Session, *, owner: User, scope: PageScope) -> list[Ad]:
    """Refused adverts launched from here, inside the subscription, untold.

    Capped: a whole batch refused at once - a policy change, a page
    restriction - would otherwise be one message per advert. The mirror's
    ``review_feedback`` is current state, so a fixed advert drops out alone.
    """
    seen = announced(db, owner=owner, kind=NoticeKind.REJECTION)
    launched = all_launched_campaign_ids(db, owner=owner)
    if not launched:
        return []
    rows = db.scalars(
        select(Ad)
        .join(AdSet, AdSet.id == Ad.adset_id)
        .join(Campaign, Campaign.id == AdSet.campaign_id)
        .where(
            Ad.owner_id == owner.id,
            Campaign.external_id.in_(launched),
            cast(Ad.review_feedback, JSONB) != cast("{}", JSONB),
        )
        .options(joinedload(Ad.adset).joinedload(AdSet.campaign))
        .order_by(Ad.synced_at.desc().nulls_last(), Ad.name)
    )
    fresh: list[Ad] = []
    for ad in rows:
        if not ad.review_feedback:
            continue
        if scope.hides(
            level=ManagedLevel.AD,
            external_id=ad.external_id,
            parent=ad.adset.external_id,
        ):
            continue
        subject = rejection_subject(
            external_id=ad.external_id, feedback=ad.review_feedback
        )
        if subject not in seen:
            fresh.append(ad)
        if len(fresh) >= MAX_REJECTIONS_PER_SWEEP:
            break
    return fresh


def owners_with_open_suggestions(db: Session, *, now: datetime) -> set[UUID]:
    return set(
        db.scalars(
            select(AgentSuggestion.owner_id)
            .where(
                AgentSuggestion.status == SuggestionStatus.PENDING,
                AgentSuggestion.expires_at > now,
            )
            .distinct()
        )
    )


def owners_with_fresh_outcomes(db: Session, *, now: datetime) -> set[UUID]:
    return set(
        db.scalars(
            select(AgentSuggestion.owner_id)
            .where(
                AgentSuggestion.status == SuggestionStatus.APPROVED,
                AgentSuggestion.assessed_at
                >= now - timedelta(hours=OUTCOME_NOTICE_HOURS),
                AgentSuggestion.outcome.in_([str(o) for o in NEWS_OUTCOMES]),
            )
            .distinct()
        )
    )


def owners_with_rejected_ads(db: Session) -> set[UUID]:
    """Every account holding an advert the provider refused. ``review_feedback``
    is emptied by the sync, not by age, so it needs no time bound."""
    return set(
        db.scalars(
            select(Ad.owner_id)
            .where(cast(Ad.review_feedback, JSONB) != cast("{}", JSONB))
            .distinct()
        )
    )


def has_been_announced(db: Session, *, owner: User, kind: str, subject: str) -> bool:
    """Whether this exact thing is finished with - delivered or given up on,
    not merely claimed, so a report that never left is still sent."""
    return (
        db.scalar(
            select(TelegramNotice.id)
            .where(
                TelegramNotice.owner_id == owner.id,
                TelegramNotice.kind == str(kind),
                TelegramNotice.subject == subject,
                settled(),
            )
            .limit(1)
        )
        is not None
    )


def sent_message_id(db: Session, *, owner: User, kind: str, subject: str) -> int:
    """The Telegram message this notice went out as, or 0."""
    return (
        db.scalar(
            select(TelegramNotice.message_id)
            .where(
                TelegramNotice.owner_id == owner.id,
                TelegramNotice.kind == str(kind),
                TelegramNotice.subject == subject,
            )
            .limit(1)
        )
        or 0
    )


__all__ = [
    "NEWS_OUTCOMES",
    "announced",
    "has_been_announced",
    "owners_with_fresh_outcomes",
    "owners_with_open_suggestions",
    "owners_with_rejected_ads",
    "rejected_ads",
    "sent_message_id",
    "settled",
    "unannounced_outcomes",
    "unannounced_suggestions",
]
