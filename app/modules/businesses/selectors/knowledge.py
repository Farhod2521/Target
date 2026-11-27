"""Reading what is known about a business: for a screen, and for a prompt.

:func:`known` is the one reading every caller starts from. :func:`brief`
turns it into the short text every model call about this business is given,
so the advert chat, the cabinet's chat and the advert writer all speak of
the same business.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.orm import Session

from app.modules.businesses.constants import (
    FACT_KEY_LABELS,
    FactKey,
    ItemStatus,
    TypeState,
)
from app.modules.businesses.models import (
    Business,
    BusinessCategory,
    BusinessKnowledge,
    BusinessSubtype,
)
from app.modules.businesses.selectors import category_label
from app.modules.businesses.services.advice import Advice, advice_of
from app.modules.businesses.services.knowledge import document_of, home, row_of
from app.modules.businesses.services.subtypes import kept

BRIEF_CHARS = 1800
BRIEF_ITEMS = 15
# Beside a prompt that already describes the business, less is enough.
LEARNED_CHARS = 1200
# What a prompt reads where nothing was ever said.
NOTHING_KNOWN = "- Nothing yet."
# What a prompt calls each fact; prompts are written in English.
FACT_PROMPT_LABELS = {
    FactKey.CUSTOMERS: "Customers",
    FactKey.AREA: "Works in",
    FactKey.DELIVERY: "Delivery",
    FactKey.GUARANTEE: "Guarantee",
    FactKey.PAYMENT: "Payment terms",
    FactKey.PRICES: "Prices",
    FactKey.HOURS: "Working hours",
    FactKey.ADDRESS: "Address",
    FactKey.CONTACTS: "Contacts",
    FactKey.ADVANTAGES: "Advantages",
    FactKey.ANSWERS: "Who answers customers and how fast",
    FactKey.OTHER: "Other",
}


@dataclass(frozen=True, slots=True)
class Known:
    """Everything known about one business at one moment."""

    business: Business
    profile: Business
    version: int
    direction: BusinessCategory | None
    type_label: str
    type_state: str
    subtype: BusinessSubtype | None
    about: dict[str, Any] | None
    items: list[dict[str, Any]] = field(default_factory=list)
    facts: dict[str, dict[str, Any]] = field(default_factory=dict)
    pending: list[dict[str, Any]] = field(default_factory=list)
    advice: Advice | None = None

    @property
    def active_items(self) -> list[dict[str, Any]]:
        return [one for one in self.items if one.get("status") == ItemStatus.ACTIVE]

    @property
    def does(self) -> str:
        """What the business does, in its own words: the knowledge first,
        the old profile's offer where nothing newer was said."""
        return str((self.about or {}).get("text") or self.profile.offer_text or "")


def _state(row: BusinessKnowledge | None, profile: Business) -> str:
    if row is not None and row.type_state != TypeState.UNSET:
        return row.type_state
    # A profile filled in by hand before any of this existed: its owner
    # picked the direction, which is as sure as a yes.
    if profile.direction_id is not None or profile.custom_category_id is not None:
        return TypeState.CONFIRMED
    return TypeState.UNSET


def known(db: Session, business: Business) -> Known:
    profile = home(db, business)
    row = row_of(db, business)
    document = document_of(row)
    subtype = row.subtype if row is not None and row.subtype_id is not None else None
    if subtype is not None:
        subtype = kept(db, subtype)
    direction = profile.direction
    state = _state(row, profile)
    return Known(
        business=business,
        profile=profile,
        version=row.version if row is not None else 0,
        direction=direction,
        # A profile we wrote ourselves carries the catalogue's general kind
        # as a placeholder: nobody chose it, so it is not said as a kind.
        type_label=(
            category_label(profile)
            if profile.category and state != TypeState.UNSET
            else ""
        ),
        type_state=state,
        subtype=subtype,
        about=document["about"],
        items=document["items"],
        facts=document["facts"],
        pending=document["pending"],
        advice=advice_of(db, direction=direction),
    )


def fact_label(key: str) -> str:
    try:
        return str(FACT_KEY_LABELS[FactKey(key)])
    except ValueError:
        return key


def _item_line(item: dict[str, Any], *, with_note: bool) -> str:
    parts = [str(item.get("name") or "")]
    if item.get("price"):
        parts.append(str(item["price"]))
    if with_note and item.get("note"):
        parts.append(str(item["note"]))
    return "  - " + " — ".join(parts)


def _sold_lines(
    view: Known, *, items: int, notes: bool, label: str = "- Sells:"
) -> list[str]:
    sold = sorted(
        view.active_items, key=lambda one: str(one.get("at") or ""), reverse=True
    )
    if not sold:
        return []
    lines = [label]
    lines += [_item_line(one, with_note=notes) for one in sold[:items]]
    if len(sold) > items:
        lines.append(f"  - (and {len(sold) - items} more)")
    return lines


def _fact_lines(view: Known) -> list[str]:
    said = [
        f"  - {FACT_PROMPT_LABELS[key]}: {held['value']}"
        for key in FactKey
        if (held := view.facts.get(key.value)) and held.get("value")
    ]
    return ["- Facts:", *said] if said else []


def brief_lines(
    view: Known, *, items: int = BRIEF_ITEMS, notes: bool = True
) -> list[str]:
    profile = view.profile
    lines = ["## Business", f"- Name: {profile.name}"]
    if view.type_label:
        kind = view.type_label
        if view.subtype is not None:
            kind += f" → {view.subtype.name}"
        if view.type_state == TypeState.GUESSED:
            kind += " (our guess, not confirmed by the business)"
        lines.append(f"- Kind: {kind}")
    if view.does:
        lines.append(f"- What it does: {view.does}")
    if profile.city:
        lines.append(f"- City: {profile.city}")
    if profile.website:
        lines.append(f"- Website: {profile.website}")
    return [
        *lines,
        *_sold_lines(view, items=items, notes=notes),
        *_fact_lines(view),
    ]


def learned_lines(
    view: Known, *, items: int = BRIEF_ITEMS, notes: bool = True
) -> list[str]:
    """What was learned of the business beyond its profile: the narrower
    kind, what it does, what it sells and the facts. For a prompt that
    already names the business, its category and its city."""
    lines: list[str] = []
    if view.subtype is not None:
        lines.append(f"- Narrower kind: {view.subtype.name}")
    about = str((view.about or {}).get("text") or "")
    if about:
        lines.append(f"- What it does: {about}")
    return [
        *lines,
        *_sold_lines(view, items=items, notes=notes, label="- Products and services:"),
        *_fact_lines(view),
    ]


def _fitted(view: Known, lines_of: Callable[..., list[str]], *, limit: int) -> str:
    """The lines within ``limit`` characters. What does not fit is dropped
    from the least needed end: the notes of the things sold first, then the
    older things."""
    text = ""
    for items, notes in (
        (BRIEF_ITEMS, True),
        (BRIEF_ITEMS, False),
        (8, False),
        (4, False),
        (0, False),
    ):
        text = "\n".join(lines_of(view, items=items, notes=notes))
        if len(text) <= limit:
            return text
    return text[:limit]


def learned(db: Session, business: Business, *, limit: int = LEARNED_CHARS) -> str:
    """What the business's people said about it earlier, as a prompt is
    given it; empty when nothing was ever said."""
    return learned_text(known(db, business), limit=limit)


def learned_text(view: Known, *, limit: int = LEARNED_CHARS) -> str:
    return _fitted(view, learned_lines, limit=limit)


def waiting_lines(view: Known) -> list[str]:
    """What a model proposed and nobody has answered yet, one line each."""
    return [
        describe(change, items=view.items)
        for proposal in view.pending
        for change in proposal.get("changes") or []
    ]


def brief(db: Session, business: Business, *, limit: int = BRIEF_CHARS) -> str:
    """The business in the words a model is given: who it is, what kind,
    what it sells and the facts about it, within ``limit`` characters. What
    does not fit is dropped from the least needed end: the notes of the
    things sold first, then the older things."""
    return _fitted(known(db, business), brief_lines, limit=limit)


def _named(document_items: list[dict[str, Any]], item_id: str) -> str:
    for item in document_items:
        if item.get("id") == item_id:
            return str(item.get("name") or "")
    return ""


def describe(change: dict[str, Any], *, items: list[dict[str, Any]]) -> str:
    """One change in the words a person is asked to say yes or no to."""
    op = change.get("op")
    if op == "set_about":
        return f"Biznes haqida: {change.get('text') or '(bo`sh)'}".replace("`", "'")
    if op == "set_fact":
        return f"{fact_label(str(change.get('key')))}: {change.get('value', '')}"
    if op == "clear_fact":
        return f"{fact_label(str(change.get('key')))}: olib tashlash"
    name = str(change.get("name") or _named(items, str(change.get("id") or "")))
    if op == "add_item":
        price = f" — {change['price']}" if change.get("price") else ""
        return f"Yangi taklif: {name}{price}"
    if op == "archive_item":
        return f"Endi sotilmaydi: {name}"
    if op == "restore_item":
        return f"Yana sotiladi: {name}"
    parts = []
    if change.get("name"):
        parts.append(f"nomi: {change['name']}")
    if "price" in change:
        parts.append(f"narxi: {change['price'] or '(yo`q)'}".replace("`", "'"))
    if "note" in change:
        parts.append(f"izoh: {change['note'] or '(yo`q)'}".replace("`", "'"))
    if "link" in change:
        parts.append(f"havola: {change['link'] or '(yo`q)'}".replace("`", "'"))
    if "kind" in change:
        parts.append("turi o'zgaradi")
    shown = _named(items, str(change.get("id") or "")) or name
    return f"«{shown}» — " + ", ".join(parts)


__all__ = [
    "NOTHING_KNOWN",
    "Known",
    "brief",
    "brief_lines",
    "describe",
    "fact_label",
    "known",
    "learned",
    "learned_lines",
    "learned_text",
    "waiting_lines",
]
