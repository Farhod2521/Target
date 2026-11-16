"""The waiting list's lines from the half-hourly guard: a price, money with
nothing back, a page down, a weak advert, a fallen rate."""

from datetime import datetime
from typing import Final, cast

from adskit import ExternalRef, ProviderName
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.routes import reverse
from app.modules.accounts.models import User
from app.modules.agent.guard_copy import (
    advised_of,
    button_label,
    buttons_of,
    guard_advice,
    guard_body,
    guard_place,
    guard_title,
)
from app.modules.agent.models import GuardAlert
from app.modules.notifications.selectors.inbox_page import InboxPage
from core.inbox import InboxItem, ItemAction, ItemKind, Level, Subject

GUARD_PREFIX: Final = "guard:"
# The cabinet's kind for each finding: the ones it already draws.
_KINDS: Final[dict[str, ItemKind]] = {
    "price": "price",
    "fruitless": "burn",
    "site_down": "landing",
    "weak_ad": "creative",
    "ctr": "creative",
    "cpm": "audience",
    "frequency": "frequency",
}
_URGENT: Final = frozenset({"price", "fruitless", "site_down"})


def open_guard_alerts(db: Session, *, owner: User) -> list[GuardAlert]:
    """The owner's open findings still waiting for an answer, the dearest
    first. One answered - left for now, or given a lower budget - stays open
    for the guard to watch and comes back here only at its next step."""
    return list(
        db.scalars(
            select(GuardAlert)
            .where(
                GuardAlert.owner_id == owner.id,
                GuardAlert.closed_at.is_(None),
                GuardAlert.answer == "",
            )
            .order_by(GuardAlert.times.desc(), GuardAlert.created_at)
        )
    )


def guard_items(
    db: Session, *, owner: User, view: InboxPage, now: datetime
) -> list[InboxItem]:
    """The page's open findings, each with its answers and the advised one."""
    accounts = {account.id for account in view.accounts}
    return [
        guard_item(row)
        for row in open_guard_alerts(db, owner=owner)
        if row.ad_account_id in accounts
        and row.adset_external_id not in view.scope.outside
    ]


def guard_key(row: GuardAlert) -> str:
    """One finding at one step: the key the phone claims a message under,
    so a step is said once and the next step is a new message."""
    return f"{GUARD_PREFIX}{row.id}:{row.step}"


def is_guard_key(key: str) -> bool:
    return key.startswith(GUARD_PREFIX)


def guard_level(row: GuardAlert) -> Level:
    if row.action == "stop" or row.kind in _URGENT:
        return "urgent"
    return "decision"


def guard_item(row: GuardAlert) -> InboxItem:
    advised = advised_of(row)
    return InboxItem(
        key=guard_key(row),
        kind=_KINDS.get(row.kind, "price"),
        level=guard_level(row),
        title=guard_title(row),
        body=guard_body(row),
        since=row.created_at,
        subject=Subject(
            ref=ExternalRef(
                provider=cast("ProviderName", row.provider),
                level="ad" if row.level == "ad" else "adset",
                id=row.external_id,
            ),
            name=row.name,
            place=guard_place(row),
        ),
        actions=tuple(
            ItemAction(
                label=button_label(answer),
                href=_href(row, answer),
                advised=answer == advised,
            )
            for answer in buttons_of(row)
        ),
        advice=guard_advice(row),
    )


def _href(row: GuardAlert, answer: str) -> str:
    if answer == "add_creative":
        return reverse("agent:guard_creative", args=[row.id])
    return f"/api/v1/agent/guard/{row.id}/{answer}"


__all__ = [
    "GUARD_PREFIX",
    "guard_item",
    "guard_items",
    "guard_key",
    "guard_level",
    "is_guard_key",
    "open_guard_alerts",
]
