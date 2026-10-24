"""The card or the line a conversation was opened from."""

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.chat.constants import SCRIPT_ASK
from app.modules.chat.selectors.refusal import refusal_quote, refused_launch_for
from core.chat.context import as_quote
from core.inbox import InboxItem


@dataclass(frozen=True, slots=True)
class Focus:
    """What this visit is about, where it is about anything."""

    card: Any = None
    item: InboxItem | None = None
    question: str = ""
    quote: dict[str, str] = field(default_factory=dict)
    refusal: str = ""


def focus_for(
    db: Session,
    *,
    owner: User,
    entitled: bool,
    now: datetime,
    suggestion_id: str = "",
    item_key: str = "",
    launch_id: str = "",
    ask: str = "",
) -> Focus:
    """The proposal, waiting-list line or refusal this conversation came from."""
    refused = refused_launch_for(
        db, owner=owner, launch_id=launch_id or _launch_in(item_key)
    )
    if refused is not None:
        return Focus(quote=refusal_quote(refused), refusal=str(refused.id))
    if not entitled:
        return Focus()
    card = _card(db, owner=owner, suggestion_id=suggestion_id)
    item = _item(db, owner=owner, item_key=item_key, now=now)
    return Focus(
        card=card,
        item=item,
        question=_question(card) or _asked(item, ask=ask),
        quote=_quote(item),
    )


def _card(db: Session, *, owner: User, suggestion_id: str) -> Any:
    from app.modules.agent.selectors import card_for, one

    if not suggestion_id:
        return None
    try:
        pk = uuid.UUID(suggestion_id)
    except ValueError:
        return None
    suggestion = one(db, owner=owner, pk=pk)
    if suggestion is None:
        return None
    return card_for(db, owner=owner, suggestion=suggestion)


def _item(
    db: Session, *, owner: User, item_key: str, now: datetime
) -> InboxItem | None:
    from app.modules.notifications.selectors import cached_inbox

    if not item_key:
        return None
    return next(
        (row for row in cached_inbox(db, owner=owner, now=now) if row.key == item_key),
        None,
    )


def _launch_in(item_key: str) -> str:
    """The launch a waiting-list line about a refusal names, or nothing."""
    kind, _sep, rest = item_key.partition(":")
    return rest.partition(":")[0] if kind == "launch" else ""


def _question(card: Any) -> str:
    if card is None:
        return ""
    return "«%(what)s» taklifini tushuntiring: nega va nima o'zgaradi?" % {
        "what": card.kind_label
    }


def _asked(item: InboxItem | None, *, ask: str) -> str:
    """The box filled from a line's own button, where the button asks for one."""
    if item is None or ask != SCRIPT_ASK or item.kind != "creative":
        return ""
    name = item.subject.name if item.subject is not None else ""
    return (
        "«%(name)s» reklamasi uchun yangi video ssenariysini yozib bering: "
        "odamlar reklamani ko'ryapti, lekin kam bosyapti."
    ) % {"name": name}


def _quote(item: InboxItem | None) -> dict[str, str]:
    if item is None:
        return {}
    return as_quote(
        title=str(item.title),
        body=str(item.body),
        target=item.subject.name if item.subject is not None else "",
    )


__all__ = ["Focus", "focus_for"]
