"""What a business has told us about itself: one document, changed in
small steps.

The document (``BusinessKnowledge.data``)::

    {
      "about":   {"text": "...", "src": "owner", "at": "<iso>"},
      "items":   [{"id": "a1b2c3d4", "name": "...", "kind": "course",
                   "price": "...", "note": "...", "link": "...",
                   "status": "active", "src": "...", "at": "<iso>"}],
      "facts":   {"delivery": {"value": "...", "src": "...", "at": "<iso>"}},
      "pending": [{"id": "...", "changes": [...], "src": "...", "by": "...",
                   "why": "...", "at": "<iso>"}]
    }

Nobody writes it whole. A write is a list of changes (``set_about``,
``add_item``, ``update_item``, ``archive_item``, ``restore_item``,
``set_fact``, ``clear_fact``), checked, then applied under a row lock; the
row's ``version`` grows by one and the journal keeps what was changed, by
whom and through what. Two chats adding to one business at the same moment
both land.

What a person said is applied (:func:`apply`). What a model worked out is
only proposed (:func:`propose`): it waits in ``pending`` until somebody of
the business says yes (:func:`confirm`) or no (:func:`reject`). Nothing is
ever removed: a thing no longer sold is archived, and a fact that was
cleared is still in the journal.
"""

import copy
import logging
import uuid
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.audit.constants import EventName
from app.modules.audit.services.emit import emit
from app.modules.businesses.constants import (
    ABOUT_CHARS,
    FACT_CHARS,
    ITEM_LINK_CHARS,
    ITEM_NAME_CHARS,
    ITEM_NOTE_CHARS,
    ITEM_PRICE_CHARS,
    MAX_ITEMS,
    MAX_PENDING,
    FactKey,
    ItemKind,
    ItemStatus,
    KnowledgeSource,
    LinkKind,
)
from app.modules.businesses.exceptions import (
    BadKnowledgeChange,
    KnowledgeFull,
    KnowledgeMoved,
    UnknownItem,
    UnknownProposal,
)
from app.modules.businesses.models import Business, BusinessKnowledge, BusinessLink
from app.modules.businesses.services.subtypes import level

logger = logging.getLogger(__name__)

SET_ABOUT = "set_about"
ADD_ITEM = "add_item"
UPDATE_ITEM = "update_item"
ARCHIVE_ITEM = "archive_item"
RESTORE_ITEM = "restore_item"
SET_FACT = "set_fact"
CLEAR_FACT = "clear_fact"
OPS = (
    SET_ABOUT,
    ADD_ITEM,
    UPDATE_ITEM,
    ARCHIVE_ITEM,
    RESTORE_ITEM,
    SET_FACT,
    CLEAR_FACT,
)

WHY_CHARS = 300
# The words of an item a change may carry, with how long each may be.
_ITEM_WORDS = {
    "name": ITEM_NAME_CHARS,
    "price": ITEM_PRICE_CHARS,
    "note": ITEM_NOTE_CHARS,
    "link": ITEM_LINK_CHARS,
}
_WORD_LABELS = {
    "name": "Nomi",
    "price": "Narxi",
    "note": "Izoh",
    "link": "Havola",
    "text": "Matn",
    "value": "Qiymat",
}


def home(db: Session, business: Business) -> Business:
    """The business whose knowledge this one reads and writes.

    A page's second ad account is a business of its own, with no page on
    its row. It sells what the page sells, so it shares the page's
    knowledge; every other business keeps its own.
    """
    if business.page_id is not None or business.ad_account_id is None:
        return business
    page_id = db.scalar(
        select(BusinessLink.page_id).where(
            BusinessLink.business_id == business.id,
            BusinessLink.kind == LinkKind.META_PAIR,
            BusinessLink.unbound_at.is_(None),
            BusinessLink.page_id.is_not(None),
        )
    )
    if page_id is None:
        return business
    of_page = db.scalar(
        select(Business).where(
            Business.user_id == business.user_id, Business.page_id == page_id
        )
    )
    return of_page or business


def row_of(db: Session, business: Business) -> BusinessKnowledge | None:
    """The knowledge kept for a business, if any was ever written."""
    return db.scalar(
        select(BusinessKnowledge).where(
            BusinessKnowledge.business_id == home(db, business).id
        )
    )


def locked_row(db: Session, business: Business) -> BusinessKnowledge:
    """The business's knowledge row, made if it is not there, held until
    the transaction ends."""
    kept = home(db, business)
    query = (
        select(BusinessKnowledge)
        .where(BusinessKnowledge.business_id == kept.id)
        .with_for_update()
    )
    row = db.scalar(query)
    if row is not None:
        return row
    try:
        with db.begin_nested():
            db.add(BusinessKnowledge(business_id=kept.id, data={}))
    except IntegrityError:
        # Made by another request between the look and the write.
        pass
    row = db.scalar(query)
    assert row is not None
    return row


def _words(change: Mapping[str, Any], name: str, limit: int) -> str:
    raw = change.get(name)
    if raw is None:
        return ""
    if not isinstance(raw, str):
        raise BadKnowledgeChange(f"{_WORD_LABELS[name]} matn bo'lsin.")
    text = " ".join(raw.split())
    if len(text) > limit:
        raise BadKnowledgeChange(f"{_WORD_LABELS[name]} {limit} belgidan oshmasin.")
    return text


def checked(change: Mapping[str, Any]) -> dict[str, Any]:
    """One change, cleaned and in the one shape the document is changed by.
    Raises :class:`BadKnowledgeChange` naming what is wrong with it."""
    if not isinstance(change, Mapping):
        raise BadKnowledgeChange
    op = str(change.get("op") or "")
    if op not in OPS:
        raise BadKnowledgeChange("Bunday o'zgarish turi yo'q.")
    if op == SET_ABOUT:
        return {"op": op, "text": _words(change, "text", ABOUT_CHARS)}
    if op in (SET_FACT, CLEAR_FACT):
        key = str(change.get("key") or "")
        if key not in set(FactKey):
            raise BadKnowledgeChange("Bunday ma'lumot turi yo'q.")
        if op == CLEAR_FACT:
            return {"op": op, "key": key}
        value = _words(change, "value", FACT_CHARS)
        if not value:
            raise BadKnowledgeChange("Qiymatni yozing.")
        return {"op": op, "key": key, "value": value}
    if op in (ARCHIVE_ITEM, RESTORE_ITEM):
        return {"op": op, "id": _item_id(change)}
    clean: dict[str, Any] = {"op": op}
    if op == UPDATE_ITEM:
        clean["id"] = _item_id(change)
    for name, limit in _ITEM_WORDS.items():
        if name in change and change[name] is not None:
            clean[name] = _words(change, name, limit)
    if "kind" in change and change["kind"] is not None:
        kind = str(change["kind"])
        if kind not in set(ItemKind):
            raise BadKnowledgeChange("Bunday taklif turi yo'q.")
        clean["kind"] = kind
    if op == ADD_ITEM and not clean.get("name"):
        raise BadKnowledgeChange("Taklif nomini yozing.")
    if op == UPDATE_ITEM:
        if "name" in clean and not clean["name"]:
            raise BadKnowledgeChange("Taklif nomi bo'sh qolmasin.")
        if len(clean) == 2:
            raise BadKnowledgeChange("Nimani o'zgartirishni yozing.")
    return clean


def _item_id(change: Mapping[str, Any]) -> str:
    item_id = str(change.get("id") or "").strip()
    if not item_id:
        raise BadKnowledgeChange("Qaysi taklif ekanini ko'rsating.")
    return item_id


def _shape(data: Mapping[str, Any] | None) -> dict[str, Any]:
    """A copy of the document with every part present."""
    held = copy.deepcopy(dict(data or {}))
    return {
        "about": held.get("about") if isinstance(held.get("about"), dict) else None,
        "items": [one for one in held.get("items") or [] if isinstance(one, dict)],
        "facts": {
            key: value
            for key, value in (held.get("facts") or {}).items()
            if isinstance(value, dict)
        },
        "pending": [one for one in held.get("pending") or [] if isinstance(one, dict)],
    }


def _item(document: dict[str, Any], item_id: str) -> dict[str, Any]:
    items: list[dict[str, Any]] = document["items"]
    for item in items:
        if item.get("id") == item_id:
            return item
    raise UnknownItem


def _same_name(
    document: dict[str, Any], name: str, *, apart_from: str = ""
) -> dict[str, Any] | None:
    key = level(name)
    items: list[dict[str, Any]] = document["items"]
    for item in items:
        if item.get("id") != apart_from and level(str(item.get("name") or "")) == key:
            return item
    return None


def _change_item(
    item: dict[str, Any], change: dict[str, Any], *, source: str, at: str
) -> bool:
    moved = False
    for name in (*_ITEM_WORDS, "kind"):
        if name in change and item.get(name, "") != change[name]:
            item[name] = change[name]
            moved = True
    if moved:
        item["src"], item["at"] = source, at
    return moved


def _apply_one(
    document: dict[str, Any], change: dict[str, Any], *, source: str, at: str
) -> dict[str, Any] | None:
    """Apply one checked change to the document in place. Answers what the
    journal keeps of it, or ``None`` when it changed nothing."""
    op = change["op"]
    if op == SET_ABOUT:
        before = (document["about"] or {}).get("text", "")
        if before == change["text"]:
            return None
        document["about"] = (
            {"text": change["text"], "src": source, "at": at}
            if change["text"]
            else None
        )
        return {"op": op, "before": before, "after": change["text"]}
    if op == SET_FACT:
        before = (document["facts"].get(change["key"]) or {}).get("value", "")
        if before == change["value"]:
            return None
        document["facts"][change["key"]] = {
            "value": change["value"],
            "src": source,
            "at": at,
        }
        return {
            "op": op,
            "key": change["key"],
            "before": before,
            "after": change["value"],
        }
    if op == CLEAR_FACT:
        held = document["facts"].pop(change["key"], None)
        if held is None:
            return None
        return {"op": op, "key": change["key"], "before": held.get("value", "")}
    if op == ADD_ITEM:
        same = _same_name(document, change["name"])
        if same is not None:
            # Named again: the same thing, perhaps with a new price. The
            # name it already has stays, whatever case it was said in now.
            before = dict(same)
            said = {key: value for key, value in change.items() if key != "name"}
            moved = _change_item(same, said, source=source, at=at)
            if same.get("status") != ItemStatus.ACTIVE:
                same["status"], same["src"], same["at"] = (
                    ItemStatus.ACTIVE.value,
                    source,
                    at,
                )
                moved = True
            if not moved:
                return None
            return {
                "op": UPDATE_ITEM,
                "id": same["id"],
                "before": _shown(before),
                "after": _shown(same),
            }
        if len(document["items"]) >= MAX_ITEMS:
            raise KnowledgeFull(
                f"Takliflar ro'yxati to'la ({MAX_ITEMS} ta). Keraksizini olib tashlang."
            )
        item = {
            "id": uuid.uuid4().hex[:8],
            "name": change["name"],
            "kind": change.get("kind", ItemKind.OTHER.value),
            "price": change.get("price", ""),
            "note": change.get("note", ""),
            "link": change.get("link", ""),
            "status": ItemStatus.ACTIVE.value,
            "src": source,
            "at": at,
        }
        document["items"].append(item)
        return {"op": op, "id": item["id"], "after": _shown(item)}
    item = _item(document, change["id"])
    before = dict(item)
    if op == UPDATE_ITEM:
        if "name" in change and _same_name(
            document, change["name"], apart_from=item["id"]
        ):
            raise BadKnowledgeChange("Bu nomli taklif allaqachon bor.")
        if not _change_item(item, change, source=source, at=at):
            return None
        return {
            "op": op,
            "id": item["id"],
            "before": _shown(before),
            "after": _shown(item),
        }
    wanted = ItemStatus.ARCHIVED if op == ARCHIVE_ITEM else ItemStatus.ACTIVE
    if item.get("status") == wanted:
        return None
    item["status"], item["src"], item["at"] = wanted.value, source, at
    return {"op": op, "id": item["id"], "name": item.get("name", "")}


def _shown(item: Mapping[str, Any]) -> dict[str, Any]:
    return {
        name: item.get(name, "")
        for name in ("name", "kind", "price", "note", "link", "status")
    }


def _write(
    db: Session,
    row: BusinessKnowledge,
    document: dict[str, Any],
    *,
    via: str,
    source: str,
    actor: User | None,
    done: list[dict[str, Any]],
    now: datetime,
) -> None:
    row.data = {key: value for key, value in document.items() if value}
    row.version += 1
    row.updated_at = now
    db.flush()
    business = db.get(Business, row.business_id)
    assert business is not None
    emit(
        db,
        owner_id=business.user_id,
        name=EventName.BUSINESS_KNOWLEDGE_CHANGED,
        aggregate_type="business",
        aggregate_id=business.id,
        payload={
            "via": via,
            "source": source,
            "by": str(actor.id) if actor is not None else "",
            "by_name": actor.full_name if actor is not None else "",
            "version": row.version,
            "changes": done,
        },
        occurred_at=now,
    )


def _source(source: str) -> str:
    if str(source) not in set(KnowledgeSource):
        raise BadKnowledgeChange("Manba noto'g'ri.")
    return str(source)


def apply(
    db: Session,
    *,
    business: Business,
    changes: Sequence[Mapping[str, Any]],
    source: str,
    actor: User | None = None,
    expected_version: int | None = None,
    now: datetime | None = None,
    via: str = "apply",
) -> BusinessKnowledge:
    """Apply what a person said to the business's knowledge; flushes.

    All of the changes land or none: one that cannot be applied raises and
    leaves the document as it was. ``expected_version`` is for a form that
    was filled over an older reading: a document changed since then raises
    :class:`KnowledgeMoved`. A chat that only adds leaves it out.
    """
    now = now or utcnow()
    source = _source(source)
    clean = [checked(change) for change in changes]
    row = locked_row(db, business)
    if expected_version is not None and expected_version != row.version:
        raise KnowledgeMoved
    document = _shape(row.data)
    at = now.isoformat()
    done = [
        kept
        for change in clean
        if (kept := _apply_one(document, change, source=source, at=at)) is not None
    ]
    if done:
        _write(
            db, row, document, via=via, source=source, actor=actor, done=done, now=now
        )
    return row


def propose(
    db: Session,
    *,
    business: Business,
    changes: Sequence[Mapping[str, Any]],
    source: str,
    actor: User | None = None,
    why: str = "",
    now: datetime | None = None,
) -> dict[str, Any] | None:
    """Keep what a model worked out until somebody of the business says yes;
    flushes. Answers the waiting proposal, or ``None`` when the changes are
    empty or the very same ones are already waiting.

    The list is short on purpose: past ``MAX_PENDING`` the oldest proposal
    nobody answered is dropped.
    """
    now = now or utcnow()
    source = _source(source)
    clean = [checked(change) for change in changes]
    if not clean:
        return None
    row = locked_row(db, business)
    document = _shape(row.data)
    if any(one.get("changes") == clean for one in document["pending"]):
        return None
    proposal = {
        "id": uuid.uuid4().hex[:8],
        "changes": clean,
        "src": source,
        "by": str(actor.id) if actor is not None else "",
        "why": " ".join(str(why or "").split())[:WHY_CHARS],
        "at": now.isoformat(),
    }
    document["pending"].append(proposal)
    dropped = document["pending"][:-MAX_PENDING]
    document["pending"] = document["pending"][-MAX_PENDING:]
    done = [{"op": "proposed", "id": proposal["id"], "changes": clean}]
    done += [{"op": "dropped", "id": one.get("id", "")} for one in dropped]
    _write(
        db, row, document, via="propose", source=source, actor=actor, done=done, now=now
    )
    return proposal


def _taken(document: dict[str, Any], proposal_id: str) -> dict[str, Any]:
    for index, one in enumerate(document["pending"]):
        if one.get("id") == proposal_id:
            return document["pending"].pop(index)  # type: ignore[no-any-return]
    raise UnknownProposal


def confirm(
    db: Session,
    *,
    business: Business,
    proposal_id: str,
    actor: User | None = None,
    now: datetime | None = None,
) -> BusinessKnowledge:
    """Somebody of the business said yes: the proposal is applied as that
    person's own words and leaves the waiting list; flushes. A proposal that
    can no longer be applied raises and stays, to be said no to."""
    now = now or utcnow()
    row = locked_row(db, business)
    document = _shape(row.data)
    proposal = _taken(document, proposal_id)
    source = str(proposal.get("src") or KnowledgeSource.ASSISTANT)
    at = now.isoformat()
    done: list[dict[str, Any]] = [{"op": "confirmed", "id": proposal_id}]
    for change in proposal.get("changes") or []:
        kept = _apply_one(document, checked(change), source=source, at=at)
        if kept is not None:
            done.append(kept)
    _write(
        db, row, document, via="confirm", source=source, actor=actor, done=done, now=now
    )
    return row


def reject(
    db: Session,
    *,
    business: Business,
    proposal_id: str,
    actor: User | None = None,
    now: datetime | None = None,
) -> BusinessKnowledge:
    """Somebody of the business said no: the proposal leaves the waiting
    list and nothing else changes; flushes."""
    now = now or utcnow()
    row = locked_row(db, business)
    document = _shape(row.data)
    proposal = _taken(document, proposal_id)
    _write(
        db,
        row,
        document,
        via="reject",
        source=str(proposal.get("src") or KnowledgeSource.ASSISTANT),
        actor=actor,
        done=[
            {
                "op": "rejected",
                "id": proposal_id,
                "changes": proposal.get("changes") or [],
            }
        ],
        now=now,
    )
    return row


def document_of(row: BusinessKnowledge | None) -> dict[str, Any]:
    """The whole document of a row, every part present, safe to read."""
    return _shape(row.data if row is not None else None)


__all__ = [
    "ADD_ITEM",
    "ARCHIVE_ITEM",
    "CLEAR_FACT",
    "OPS",
    "RESTORE_ITEM",
    "SET_ABOUT",
    "SET_FACT",
    "UPDATE_ITEM",
    "apply",
    "checked",
    "confirm",
    "document_of",
    "home",
    "locked_row",
    "propose",
    "reject",
    "row_of",
]
