"""What is broken in one account's plumbing that the agent may put right. Detection only."""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from core.agent.autofix import LEADS_RECOVERABLE, PAGE_UNSUBSCRIBED


@dataclass(frozen=True, slots=True)
class Trouble:
    """One thing that is wrong, named the way the fix table names it."""

    trigger: str
    target_id: str = ""
    detail: dict[str, Any] = field(default_factory=dict)
    previous: dict[str, Any] = field(default_factory=dict)


def repairable(db: Session, *, owner: User, now: datetime) -> tuple[Trouble, ...]:
    """Everything wrong here that has an entry in the fix table, in the order it is fixed."""
    found = [_page(db, owner=owner), _leads(db, owner=owner, now=now)]
    return tuple(item for item in found if item is not None)


def _page(db: Session, *, owner: User) -> Trouble | None:
    from app.modules.integrations.selectors import active_page

    page = active_page(db, owner=owner)
    if page is None or page.leadgen_subscribed:
        return None
    return Trouble(
        trigger=PAGE_UNSUBSCRIBED,
        target_id=page.external_id,
        previous={"leadgen_subscribed": False},
    )


def _leads(db: Session, *, owner: User, now: datetime) -> Trouble | None:
    from app.modules.leads.selectors import delivery_trouble

    lost = delivery_trouble(db, owner=owner, now=now).recoverable
    if not lost:
        return None
    return Trouble(trigger=LEADS_RECOVERABLE, detail={"count": lost})


__all__ = ["Trouble", "repairable"]
