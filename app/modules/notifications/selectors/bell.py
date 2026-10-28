"""The two numbers every page carries, and the minute-long cache behind them.

The bell answers "what is new since I last looked"; the badge answers "what
have I not answered". The list is cached for a minute per reader and page,
and the screen that draws it in full writes its fresh copy back.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from adskit import ExternalRef
from metaads import PROVIDER as META
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.cache import cache
from app.common.i18n import get_language
from app.modules.accounts.models import User
from app.modules.integrations.models import AdAccount, PageAccount
from app.modules.notifications.selectors import seen_keys
from app.modules.notifications.selectors.inbox import inbox
from core.inbox import InboxItem, ItemAction, Subject, answerable, unseen

CACHE_SECONDS = 60
CACHE_KEY = "inbox:{owner_id}:{language}"

# How many lines the bell's panel holds: a preview, the screen is the list.
PANEL_ITEMS = 6


@dataclass(frozen=True, slots=True)
class Counts:
    """What the two badges say. Both nought is the ordinary answer."""

    new: int
    waiting: int


def counts_for(db: Session, *, owner: User, now: datetime) -> Counts:
    """The bell's number and the navigation's, building the list if it must."""
    return counted(db, owner=owner, items=cached_inbox(db, owner=owner, now=now))


def warm_counts(db: Session, *, owner: User) -> Counts | None:
    """The two numbers if they can be had cheaply, and ``None`` if not."""
    held = _held(db, owner=owner)
    if held is None:
        return None
    return counted(db, owner=owner, items=held)


def counted(db: Session, *, owner: User, items: tuple[InboxItem, ...]) -> Counts:
    return Counts(
        new=len(unseen(items, seen=seen_keys(db, owner=owner))),
        waiting=len(answerable(items)),
    )


def cached_inbox(db: Session, *, owner: User, now: datetime) -> tuple[InboxItem, ...]:
    """The list, from the cache when it is warm and from the source when it is not."""
    page = _page(db, owner=owner)
    held = _held(db, owner=owner, page=page)
    if held is not None:
        return held
    return remember(db, owner=owner, items=inbox(db, owner=owner, now=now), page=page)


def remember(
    db: Session,
    *,
    owner: User,
    items: tuple[InboxItem, ...],
    page: str | None = None,
) -> tuple[InboxItem, ...]:
    """Put a freshly assembled list where the badges will find it."""
    cache.set(
        _key(owner=owner),
        {
            "page": _page(db, owner=owner) if page is None else page,
            "items": [item_to_dict(item) for item in items],
        },
        CACHE_SECONDS,
    )
    return items


def forget(*, owner: User) -> None:
    """Drop this reader's cached list. For a caller that has just changed it."""
    cache.delete(_key(owner=owner))


def watching(db: Session, *, owner: User) -> bool:
    """Whether this cabinet has an account whose advertising has been read.

    What the bell's empty state may claim: "Hammasi joyida" only where it
    looked at something.
    """
    return (
        db.scalar(
            select(AdAccount.id)
            .where(
                AdAccount.owner_id == owner.id,
                AdAccount.provider == META,
                AdAccount.is_active.is_(True),
                AdAccount.synced_at.is_not(None),
            )
            .limit(1)
        )
        is not None
    )


def item_to_dict(item: InboxItem) -> dict[str, Any]:
    """One item as plain JSON values, for the cache and the API alike."""
    subject = item.subject
    return {
        "key": item.key,
        "kind": item.kind,
        "level": item.level,
        "title": item.title,
        "body": item.body,
        "since": item.since.isoformat() if item.since is not None else None,
        "action": item.action,
        "href": item.href,
        "method": item.method,
        "subject": {
            "provider": subject.ref.provider,
            "level": subject.ref.level,
            "id": subject.ref.id,
            "name": subject.name,
            "code": subject.code,
        }
        if subject is not None
        else None,
        "actions": [
            {
                "label": choice.label,
                "href": choice.href,
                "advised": choice.advised,
                "confirm": choice.confirm,
            }
            for choice in item.actions
        ],
    }


def item_from_dict(raw: dict[str, Any]) -> InboxItem:
    subject = raw.get("subject")
    since = raw.get("since")
    return InboxItem(
        key=raw["key"],
        kind=raw["kind"],
        level=raw["level"],
        title=raw["title"],
        body=raw["body"],
        since=datetime.fromisoformat(since) if since else None,
        action=raw.get("action", ""),
        href=raw.get("href", ""),
        method=raw.get("method", "get"),
        subject=Subject(
            ref=ExternalRef(
                provider=subject["provider"], level=subject["level"], id=subject["id"]
            ),
            name=subject.get("name", ""),
            code=subject.get("code", ""),
        )
        if subject
        else None,
        actions=tuple(ItemAction(**choice) for choice in raw.get("actions", ())),
    )


def _held(
    db: Session, *, owner: User, page: str | None = None
) -> tuple[InboxItem, ...] | None:
    """The cached list, if it was built for the page the owner is on now."""
    held = cache.get(_key(owner=owner))
    if not isinstance(held, dict):
        return None
    showing = _page(db, owner=owner) if page is None else page
    if held.get("page") != showing:
        return None
    try:
        return tuple(item_from_dict(raw) for raw in held["items"])
    except (KeyError, TypeError, ValueError):
        return None


def _page(db: Session, *, owner: User) -> str:
    """Which page the cabinet is pointed at. One indexed read."""
    found = db.scalar(
        select(PageAccount.id)
        .where(
            PageAccount.owner_id == owner.id,
            PageAccount.is_active.is_(True),
            PageAccount.is_current.is_(True),
        )
        .limit(1)
    )
    return str(found or "")


def _key(*, owner: User) -> str:
    return CACHE_KEY.format(owner_id=owner.id, language=get_language() or "")


__all__ = [
    "CACHE_SECONDS",
    "PANEL_ITEMS",
    "Counts",
    "cached_inbox",
    "counted",
    "counts_for",
    "forget",
    "item_from_dict",
    "item_to_dict",
    "remember",
    "warm_counts",
    "watching",
]
