"""Everything one cabinet is waiting on, in one shape and one order."""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from adskit import ExternalRef

ItemKind = Literal[
    "suggestion",
    "connection",
    "refusal",
    "trouble",
    "subscription",
    "setup",
    "launch",
    "figures",
    "leads",
    "cap",
    "unpriced",
    "attribution",
    "ranking",
    "advice",
    "repair",
    "wait",
    "landing",
    "creative",
    "audience",
    "lead_gap",
    "sweep",
    "unheard_page",
    "burn",
    "watch",
    "frequency",
    "meta_hold",
    "account_blocked",
    "support",
    "feedback",
    "checkup",
]

Level = Literal["urgent", "decision", "news"]

LEVELS: tuple[Level, ...] = ("urgent", "decision", "news")

ANSWERABLE: frozenset[str] = frozenset({"urgent", "decision"})


@dataclass(frozen=True, slots=True)
class Subject:
    """The advertising object one waiting item is about."""

    ref: ExternalRef
    name: str = ""
    code: str = ""


@dataclass(frozen=True, slots=True)
class ItemAction:
    """One of several buttons under an item, for the kind that offers a choice."""

    label: str
    href: str = ""
    advised: bool = False
    confirm: str = ""


@dataclass(frozen=True, slots=True)
class InboxItem:
    """One thing waiting for this cabinet's owner."""

    key: str
    kind: ItemKind
    level: Level
    title: str
    body: str
    since: datetime | None = None
    action: str = ""
    href: str = ""
    subject: Subject | None = None
    method: Literal["get", "post"] = "get"
    actions: tuple[ItemAction, ...] = ()


def ordered(items: Iterable[InboxItem]) -> tuple[InboxItem, ...]:
    """Worst first, and within a level the one that has waited longest."""
    return tuple(
        sorted(items, key=lambda item: (LEVELS.index(item.level), _rank(item.since)))
    )


def unseen(
    items: Iterable[InboxItem], *, seen: frozenset[str]
) -> tuple[InboxItem, ...]:
    """What this reader has not been shown yet, in the same order."""
    return tuple(item for item in ordered(items) if item.key not in seen)


def answerable(items: Iterable[InboxItem]) -> tuple[InboxItem, ...]:
    """The ones that are a question. What the navigation counts."""
    return tuple(item for item in ordered(items) if item.level in ANSWERABLE)


def of_level(items: Iterable[InboxItem], *, level: Level) -> tuple[InboxItem, ...]:
    """One band of the list, still in order."""
    return tuple(item for item in ordered(items) if item.level == level)


def without_kind(
    items: Iterable[InboxItem], *, kind: ItemKind
) -> tuple[InboxItem, ...]:
    """Everything except one kind, for a surface that draws that kind itself."""
    return tuple(item for item in ordered(items) if item.kind != kind)


def keys(items: Iterable[InboxItem]) -> frozenset[str]:
    """Every key in this list - what a reader's "seen" set is written from."""
    return frozenset(item.key for item in items)


def _rank(since: datetime | None) -> tuple[int, float]:
    """Sortable position for a moment that may not exist."""
    if since is None:
        return (1, 0.0)
    return (0, since.timestamp())


__all__ = [
    "ANSWERABLE",
    "LEVELS",
    "InboxItem",
    "ItemKind",
    "Level",
    "Subject",
    "answerable",
    "keys",
    "of_level",
    "ordered",
    "unseen",
    "without_kind",
]
