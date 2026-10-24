"""The actions an answer is allowed to end by offering: open proposals, by short key."""

import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.ads.selectors.page_boundary import PageScope
from app.modules.agent.constants import OPEN_STATUSES
from app.modules.agent.models import AgentSuggestion
from app.modules.chat.constants import OFFERS_IN_CONTEXT
from app.modules.chat.models import ChatMessage
from app.modules.chat.selectors.fence import outside_targets
from app.modules.chat.selectors.scope import current_page_scope
from core.chat.route import Section

ACTIONABLE: Final[frozenset[Section]] = frozenset(
    {"campaigns", "adsets", "suggestions"}
)

PREFIX: Final = "A"


@dataclass(frozen=True, slots=True)
class Choice:
    """One offerable action: what the model sees, and what the product does."""

    key: str
    pk: str
    label: str
    target: str
    rule: str


def offers_for(
    db: Session,
    *,
    owner: User | None,
    entitled: bool,
    wants: frozenset[Section] | None,
    now: datetime | None,
    scope: PageScope | None = None,
) -> tuple[Choice, ...]:
    """The open proposals this question could end by offering. Usually none."""
    from app.modules.agent.selectors import pending_cards

    if not entitled or owner is None or now is None:
        return ()
    if wants is None or not (wants & ACTIONABLE):
        return ()
    cards = _inside(
        db, owner=owner, cards=pending_cards(db, owner=owner, now=now), scope=scope
    )[:OFFERS_IN_CONTEXT]
    return tuple(
        _choice(card=card, index=index) for index, card in enumerate(cards, start=1)
    )


def _inside(
    db: Session, *, owner: User, cards: list[Any], scope: PageScope | None
) -> list[Any]:
    """The cards whose object is not on a page outside the subscription."""
    if not cards:
        return cards
    targets = {
        str(pk): (level, external_id, parent)
        for pk, level, external_id, parent in db.execute(
            select(
                AgentSuggestion.id,
                AgentSuggestion.target_level,
                AgentSuggestion.target_external_id,
                AgentSuggestion.target_parent_id,
            ).where(
                AgentSuggestion.owner_id == owner.id,
                AgentSuggestion.id.in_([uuid.UUID(card.pk) for card in cards]),
            )
        )
    }
    hidden = outside_targets(
        db,
        owner=owner,
        scope=scope or current_page_scope(db, owner=owner),
        targets=targets.values(),
    )
    return [
        card
        for card in cards
        if card.pk in targets and targets[card.pk][:2] not in hidden
    ]


def _choice(*, card: Any, index: int) -> Choice:
    return Choice(
        key=f"{PREFIX}{index}",
        pk=card.pk,
        label=str(card.action_label),
        target=card.target_name,
        rule=str(card.rule_label),
    )


def picked(
    *, keys: tuple[str, ...], offers: list[dict[str, str]]
) -> list[dict[str, str]]:
    """The offers the answer named, in the order it named them."""
    by_key = {str(item.get("key", "")): item for item in offers}
    return [by_key[key] for key in keys if key in by_key]


def offers_on(db: Session, *, owner: User, message_id: str) -> tuple[Choice, ...]:
    """What one finished answer ended by offering, read back off its row."""
    try:
        key = uuid.UUID(str(message_id))
    except ValueError:
        return ()
    row = db.scalar(
        select(ChatMessage).where(
            ChatMessage.owner_id == owner.id, ChatMessage.id == key
        )
    )
    if row is None:
        return ()
    return tuple(
        Choice(
            key=str(item.get("key", "")),
            pk=str(item.get("pk", "")),
            label=str(item.get("label", "")),
            target=str(item.get("target", "")),
            rule=str(item.get("rule", "")),
        )
        for item in (row.choices or ())
        if item.get("pk")
    )


def with_choices(db: Session, *, owner: User, messages: Iterable[Any]) -> list[Any]:
    """The thread, with each answer's still-pressable buttons attached."""
    drawn = list(messages)
    live = still_open(
        db,
        owner=owner,
        pks=[
            str(choice["pk"])
            for message in drawn
            for choice in (message.choices or ())
            if choice.get("pk")
        ],
    )
    for message in drawn:
        message.offers = [
            choice
            for choice in (message.choices or ())
            if str(choice.get("pk", "")) in live
        ]
    return drawn


def still_open(db: Session, *, owner: User, pks: list[str]) -> frozenset[str]:
    """Which of these proposals can still be answered."""
    keys = []
    for pk in pks:
        try:
            keys.append(uuid.UUID(pk))
        except ValueError:
            continue
    if not keys:
        return frozenset()
    return frozenset(
        str(pk)
        for pk in db.scalars(
            select(AgentSuggestion.id).where(
                AgentSuggestion.owner_id == owner.id,
                AgentSuggestion.id.in_(keys),
                AgentSuggestion.status.in_(OPEN_STATUSES),
            )
        )
    )


__all__ = [
    "ACTIONABLE",
    "Choice",
    "offers_for",
    "offers_on",
    "picked",
    "still_open",
    "with_choices",
]
