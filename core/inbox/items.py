"""Everything one cabinet is waiting on, in one shape and one order."""

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Final, Literal

from adskit import ExternalRef

ItemKind = Literal[
    "suggestion",
    "stop",
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

# How a left line is written among the seen keys, and how long it stays away.
LEFT_PREFIX: Final = "left:"
LEFT_DAYS: Final = 7

# What the agent would do about a line, by what the line is. The proposals carry
# their own, and a kind with no general answer says nothing.
ADVICE: Final[dict[str, str]] = {
    "stop": "Sababini bartaraf eting, reklama o'zi davom etadi.",
    "connection": "Facebook'ni qayta ulang, raqamlar va murojaatlar yana keladi.",
    "refusal": "Rad etish sababini o'qing va reklamani tuzatib qayta yuboring.",
    "trouble": "Muammoni shu reklamaning sahifasidan tuzating.",
    "subscription": "Obunani yangilang, reklamalar to'xtab qolmasin.",
    "setup": "Sozlashni oxiriga yetkazing, shunda agent ishlay boshlaydi.",
    "launch": "Javoblaringiz saqlangan: xatoni tuzatib, qayta yuboring.",
    "figures": "Raqamlarni yangilang, eski raqam bilan qaror qilmang.",
    "leads": "Murojaatlarni hozir tiklang, muddati o'tsa yo'qoladi.",
    "cap": "Xarajat chegarasini oshiring yoki olib tashlang.",
    "unpriced": "Xarajat ko'rinishi uchun reklama akkauntini tekshiring.",
    "lead_gap": "Ulanishni tekshiring, murojaatlar kabinetga tushmayapti.",
    "sweep": "Tekshiruvni qayta ishga tushiring.",
    "unheard_page": "Sahifa ulanishini tekshiring.",
    "meta_hold": "Meta'da shaxsingizni tasdiqlang, o'zgarishlar yana qabul qilinadi.",
    "account_blocked": "Meta'da akkaunt holatini tekshiring: bu faqat u yerda tuzatiladi.",
    "checkup": "Agent tarixini ko'rib chiqing yoki AI dan so'rang.",
    "watch": "Rasm yoki formani yangilang, keyin reklamani qayta yoqing.",
    "frequency": "Yangi rasm qo'shing, reklama yangi odamlarga yetadi.",
    "ranking": "Rasm va matnni yangilang, baho shundan ko'tariladi.",
    "creative": "Rasm yoki matnni almashtiring.",
    "audience": "Auditoriyani kengaytiring yoki o'zgartiring.",
    "landing": "Reklama ochadigan sahifa yoki formani tekshiring.",
}

# What says which network without a subject: these lines are Meta's own.
META_KINDS: Final = frozenset({"connection", "meta_hold", "account_blocked"})


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
    advice: str = ""
    network: str = ""


def advised(item: InboxItem) -> InboxItem:
    """The line with the agent's word and its network, where they can be told."""
    network = item.network
    if not network:
        network = item.subject.ref.provider if item.subject is not None else ""
    if not network and item.kind in META_KINDS:
        network = "meta"
    return replace(
        item, advice=item.advice or ADVICE.get(item.kind, ""), network=network
    )


def leavable(item: InboxItem) -> bool:
    """Whether "leave it as it is" is an answer: never for what is broken now."""
    return item.level != "urgent" and item.kind != "suggestion"


def left_key(key: str) -> str:
    """The seen-table key a left line goes under; an item's own key may be longer."""
    return f"{LEFT_PREFIX}{hashlib.sha256(key.encode()).hexdigest()[:40]}"


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
    "ADVICE",
    "ANSWERABLE",
    "LEFT_DAYS",
    "LEFT_PREFIX",
    "LEVELS",
    "InboxItem",
    "ItemKind",
    "Level",
    "Subject",
    "advised",
    "answerable",
    "keys",
    "leavable",
    "left_key",
    "of_level",
    "ordered",
    "unseen",
    "without_kind",
]
