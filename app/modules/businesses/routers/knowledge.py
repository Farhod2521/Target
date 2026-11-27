"""``/api/v3/businesses/{id}/knowledge``: what a business has told us about
itself, read and changed.

Reading is for the owner and for everybody who works in the business.
Changing is for the owner and for a member who may change something there
(an ``edit`` grant in any area): a sales manager learns a new price before
anybody else does. Every write answers the whole knowledge as it stands
after it, so a screen never has to read again.
"""

import uuid
from datetime import datetime
from typing import Any

from fastapi import APIRouter
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import CurrentUser, Db
from app.modules.accounts.models import User
from app.modules.audit.constants import EVENT_NAME_LABELS, EventName
from app.modules.audit.models import Event
from app.modules.businesses import selectors
from app.modules.businesses.constants import (
    ABOUT_CHARS,
    ADVISED_GOAL_LABELS,
    FACT_CHARS,
    FACT_KEY_LABELS,
    ITEM_KIND_LABELS,
    ITEM_LINK_CHARS,
    ITEM_NAME_CHARS,
    ITEM_NOTE_CHARS,
    ITEM_PRICE_CHARS,
    KNOWLEDGE_SOURCE_LABELS,
    MAX_ITEMS,
    AdvisedGoal,
    FactKey,
    GrantArea,
    GrantLevel,
    ItemKind,
    KnowledgeSource,
    SubtypeOrigin,
    TypeState,
)
from app.modules.businesses.exceptions import (
    NoAccess,
    UnknownDirection,
    UnknownSubtype,
)
from app.modules.businesses.models import BusinessSubtype
from app.modules.businesses.schemas.knowledge import (
    AboutOut,
    ChangesIn,
    ChoiceOut,
    FactOut,
    ItemOut,
    KindIn,
    KindOut,
    KnowledgeAdviceOut,
    KnowledgeCatalogOut,
    KnowledgeEventOut,
    KnowledgeHistoryOut,
    KnowledgeOut,
    KnowledgeProposalOut,
    SubtypeOut,
    SubtypesOut,
)
from app.modules.businesses.selectors.access import Access, access_for
from app.modules.businesses.selectors.knowledge import (
    Known,
    describe,
    fact_label,
    known,
)
from app.modules.businesses.services import kinds as kind_services
from app.modules.businesses.services import knowledge as knowledge_services
from app.modules.businesses.services import subtypes as subtype_services

router = APIRouter(prefix="/businesses", tags=["businesses v3"])

HISTORY_NAMES = (EventName.BUSINESS_KNOWLEDGE_CHANGED, EventName.BUSINESS_TYPE_SET)


def _label(labels: dict[Any, str], key: str) -> str:
    for known_key, label in labels.items():
        if str(known_key) == key:
            return label
    return key


def _at(raw: object) -> datetime | None:
    try:
        return datetime.fromisoformat(str(raw))
    except ValueError:
        return None


def _may_edit(access: Access) -> bool:
    return access.is_owner or any(
        access.reaches(area, GrantLevel.EDIT) for area in GrantArea
    )


def _editor(db: Session, business_id: uuid.UUID, user: User) -> Access:
    access = access_for(db, business_id=business_id, user=user)
    if not _may_edit(access):
        raise NoAccess
    return access


def _source(access: Access) -> str:
    return KnowledgeSource.OWNER if access.is_owner else KnowledgeSource.MEMBER


def _goal(key: str) -> ChoiceOut:
    return ChoiceOut(key=key, label=_label(ADVISED_GOAL_LABELS, key))


def _subtype(row: BusinessSubtype) -> SubtypeOut:
    return SubtypeOut(id=row.id, name=row.name, is_checked=row.is_checked)


def _out(view: Known, access: Access) -> KnowledgeOut:
    direction = view.direction
    advice = view.advice
    return KnowledgeOut(
        business_id=view.business.id,
        kept_by=view.profile.id,
        version=view.version,
        may_edit=_may_edit(access),
        kind=KindOut(
            direction=ChoiceOut(key=direction.key, label=direction.label)
            if direction is not None
            else None,
            label=view.type_label,
            state=view.type_state,
            subtype=_subtype(view.subtype) if view.subtype is not None else None,
        ),
        does=view.does,
        about=AboutOut(
            text=str(view.about.get("text") or ""),
            source=str(view.about.get("src") or ""),
            source_label=_label(KNOWLEDGE_SOURCE_LABELS, str(view.about.get("src"))),
            at=_at(view.about.get("at")),
        )
        if view.about
        else None,
        items=[
            ItemOut(
                id=str(item.get("id") or ""),
                name=str(item.get("name") or ""),
                kind=str(item.get("kind") or ItemKind.OTHER),
                kind_label=_label(ITEM_KIND_LABELS, str(item.get("kind"))),
                price=str(item.get("price") or ""),
                note=str(item.get("note") or ""),
                link=str(item.get("link") or ""),
                status="archived" if item.get("status") == "archived" else "active",
                source=str(item.get("src") or ""),
                source_label=_label(KNOWLEDGE_SOURCE_LABELS, str(item.get("src"))),
                at=_at(item.get("at")),
            )
            for item in view.items
        ],
        facts=[
            FactOut(
                key=key.value,
                label=FACT_KEY_LABELS[key],
                value=str(view.facts[key.value].get("value") or ""),
                source=str(view.facts[key.value].get("src") or ""),
                source_label=_label(
                    KNOWLEDGE_SOURCE_LABELS, str(view.facts[key.value].get("src"))
                ),
                at=_at(view.facts[key.value].get("at")),
            )
            for key in FactKey
            if key.value in view.facts
        ],
        pending=[
            KnowledgeProposalOut(
                id=str(one.get("id") or ""),
                source=str(one.get("src") or ""),
                source_label=_label(KNOWLEDGE_SOURCE_LABELS, str(one.get("src"))),
                why=str(one.get("why") or ""),
                at=_at(one.get("at")),
                lines=[
                    describe(change, items=view.items)
                    for change in one.get("changes") or []
                ],
                changes=list(one.get("changes") or []),
            )
            for one in view.pending
        ],
        advice=KnowledgeAdviceOut(
            goal_first=_goal(advice.goal_first),
            reason_first=advice.reason_first,
            goal_second=_goal(advice.goal_second) if advice.goal_second else None,
            when_second=advice.when_second,
            never_say=advice.never_say,
        )
        if advice is not None
        else None,
    )


@router.get("/knowledge/catalog", response_model=KnowledgeCatalogOut)
def knowledge_catalog(db: Db, user: CurrentUser) -> KnowledgeCatalogOut:
    """The lists a knowledge form is built from, with the limits it holds."""
    return KnowledgeCatalogOut(
        directions=[
            ChoiceOut(key=row.key, label=row.label)
            for row in selectors.offered_directions(db)
        ],
        item_kinds=[
            ChoiceOut(key=kind.value, label=ITEM_KIND_LABELS[kind]) for kind in ItemKind
        ],
        fact_keys=[
            ChoiceOut(key=key.value, label=FACT_KEY_LABELS[key]) for key in FactKey
        ],
        sources=[
            ChoiceOut(key=source.value, label=KNOWLEDGE_SOURCE_LABELS[source])
            for source in KnowledgeSource
        ],
        goals=[
            ChoiceOut(key=goal.value, label=ADVISED_GOAL_LABELS[goal])
            for goal in AdvisedGoal
        ],
        ops=list(knowledge_services.OPS),
        limits={
            "items": MAX_ITEMS,
            "about": ABOUT_CHARS,
            "item_name": ITEM_NAME_CHARS,
            "item_price": ITEM_PRICE_CHARS,
            "item_note": ITEM_NOTE_CHARS,
            "item_link": ITEM_LINK_CHARS,
            "fact": FACT_CHARS,
        },
    )


@router.get("/{business_id}/knowledge", response_model=KnowledgeOut)
def knowledge(business_id: uuid.UUID, db: Db, user: CurrentUser) -> KnowledgeOut:
    """What is known about the business: its kind, what it sells, the facts,
    the changes waiting for a yes, and what the office advises its kind."""
    access = access_for(db, business_id=business_id, user=user)
    return _out(known(db, access.business), access)


@router.post("/{business_id}/knowledge/changes", response_model=KnowledgeOut)
def change_knowledge(
    business_id: uuid.UUID, body: ChangesIn, db: Db, user: CurrentUser
) -> KnowledgeOut:
    """Apply a list of small changes, all or none."""
    access = _editor(db, business_id, user)
    knowledge_services.apply(
        db,
        business=access.business,
        changes=[change.model_dump(exclude_none=True) for change in body.changes],
        source=_source(access),
        actor=user,
        expected_version=body.version,
    )
    db.commit()
    return _out(known(db, access.business), access)


@router.post(
    "/{business_id}/knowledge/proposals/{proposal_id}/confirm",
    response_model=KnowledgeOut,
)
def confirm_proposal(
    business_id: uuid.UUID, proposal_id: str, db: Db, user: CurrentUser
) -> KnowledgeOut:
    """Say yes to a change a chat proposed: it is applied."""
    access = _editor(db, business_id, user)
    knowledge_services.confirm(
        db, business=access.business, proposal_id=proposal_id, actor=user
    )
    db.commit()
    return _out(known(db, access.business), access)


@router.post(
    "/{business_id}/knowledge/proposals/{proposal_id}/reject",
    response_model=KnowledgeOut,
)
def reject_proposal(
    business_id: uuid.UUID, proposal_id: str, db: Db, user: CurrentUser
) -> KnowledgeOut:
    """Say no to a change a chat proposed: it is dropped."""
    access = _editor(db, business_id, user)
    knowledge_services.reject(
        db, business=access.business, proposal_id=proposal_id, actor=user
    )
    db.commit()
    return _out(known(db, access.business), access)


@router.put("/{business_id}/kind", response_model=KnowledgeOut)
def set_kind(
    business_id: uuid.UUID, body: KindIn, db: Db, user: CurrentUser
) -> KnowledgeOut:
    """Say what kind of business this is: a direction, and optionally a
    narrower kind under it, by id or by name. A name that is not there yet
    is made. For the owner, and for a member who may change the adverts."""
    access = access_for(db, business_id=business_id, user=user)
    if not (access.is_owner or access.reaches(GrantArea.ADS, GrantLevel.EDIT)):
        # The kind picks the catalogue every advert is built from: it is the
        # owner's to say, and theirs who runs the adverts.
        raise NoAccess
    direction = selectors.direction_by_key(db, body.direction)
    if direction is None or not direction.is_active:
        raise UnknownDirection
    subtype = None
    if body.subtype_id is not None:
        subtype = db.get(BusinessSubtype, body.subtype_id)
        if subtype is None:
            raise UnknownSubtype
    elif body.subtype and body.subtype.strip():
        subtype, _ = subtype_services.ensure(
            db,
            direction=direction,
            name=body.subtype,
            origin=SubtypeOrigin.AI,
            actor=user,
        )
    kind_services.set_kind(
        db,
        business=access.business,
        direction=direction,
        subtype=subtype,
        state=TypeState.CONFIRMED,
        source=_source(access),
        actor=user,
    )
    db.commit()
    return _out(known(db, access.business), access)


@router.get("/{business_id}/knowledge/subtypes", response_model=SubtypesOut)
def subtypes(business_id: uuid.UUID, db: Db, user: CurrentUser) -> SubtypesOut:
    """The narrower kinds under the business's direction, for a picker."""
    access = access_for(db, business_id=business_id, user=user)
    direction = knowledge_services.home(db, access.business).direction
    if direction is None:
        return SubtypesOut(direction=None, subtypes=[])
    rows = db.scalars(
        select(BusinessSubtype)
        .where(
            BusinessSubtype.direction_id == direction.id,
            BusinessSubtype.is_active.is_(True),
            BusinessSubtype.merged_into_id.is_(None),
        )
        .order_by(BusinessSubtype.name_key)
    )
    return SubtypesOut(
        direction=ChoiceOut(key=direction.key, label=direction.label),
        subtypes=[_subtype(row) for row in rows],
    )


def _shown(held: object) -> dict[str, Any]:
    return held if isinstance(held, dict) else {}


def _journal_line(entry: dict[str, Any]) -> str:
    """One journal entry of a knowledge change, in words."""
    op = entry.get("op")
    after, before = _shown(entry.get("after")), _shown(entry.get("before"))
    if op == "set_about":
        return f"Biznes haqida: {entry.get('after') or '(olib tashlandi)'}"
    if op == "set_fact":
        was = f"{entry['before']} → " if entry.get("before") else ""
        return f"{fact_label(str(entry.get('key')))}: {was}{entry.get('after', '')}"
    if op == "clear_fact":
        return f"{fact_label(str(entry.get('key')))}: olib tashlandi"
    if op == "add_item":
        price = f" — {after['price']}" if after.get("price") else ""
        return f"Yangi taklif: {after.get('name', '')}{price}"
    if op == "update_item":
        moved = [
            f"{label}: {before.get(name) or '—'} → {after.get(name) or '—'}"
            for name, label in (
                ("name", "nomi"),
                ("price", "narxi"),
                ("note", "izoh"),
                ("link", "havola"),
                ("kind", "turi"),
                ("status", "holati"),
            )
            if before.get(name) != after.get(name)
        ]
        return f"«{after.get('name') or before.get('name', '')}» — " + ", ".join(moved)
    if op == "archive_item":
        return f"Endi sotilmaydi: {entry.get('name', '')}"
    if op == "restore_item":
        return f"Yana sotiladi: {entry.get('name', '')}"
    if op == "proposed":
        return f"Tasdiqlash uchun taklif qilindi ({len(entry.get('changes') or [])} ta o'zgarish)"
    if op == "confirmed":
        return "Taklif tasdiqlandi"
    if op == "rejected":
        return "Taklif rad etildi"
    if op == "dropped":
        return "Javobsiz qolgan eski taklif olib tashlandi"
    return str(op or "")


@router.get("/{business_id}/knowledge/history", response_model=KnowledgeHistoryOut)
def knowledge_history(
    business_id: uuid.UUID, db: Db, user: CurrentUser, limit: int = 100
) -> KnowledgeHistoryOut:
    """What was changed in the business's knowledge and its kind, by whom
    and through what, newest first."""
    access = access_for(db, business_id=business_id, user=user)
    kept = knowledge_services.home(db, access.business)
    events = db.scalars(
        select(Event)
        .where(
            Event.owner_id == kept.user_id,
            Event.aggregate_type == "business",
            Event.aggregate_id == str(kept.id),
            Event.name.in_([str(name) for name in HISTORY_NAMES]),
        )
        .order_by(Event.occurred_at.desc(), Event.created_at.desc())
        .limit(max(1, min(limit, 500)))
    )
    items = []
    for event in events:
        payload = event.payload if isinstance(event.payload, dict) else {}
        if event.name == EventName.BUSINESS_TYPE_SET:
            kind = str(payload.get("direction_label") or "")
            if payload.get("subtype_name"):
                kind += f" → {payload['subtype_name']}"
            lines = [f"Biznes turi: {kind}"]
        else:
            lines = [
                _journal_line(entry)
                for entry in payload.get("changes") or []
                if isinstance(entry, dict)
            ]
        source = str(payload.get("source") or "")
        items.append(
            KnowledgeEventOut(
                id=event.id,
                at=event.occurred_at,
                kind=event.name.split(".", 1)[-1],
                label=_label(EVENT_NAME_LABELS, event.name),
                via=str(payload.get("via") or ""),
                source=source,
                source_label=_label(KNOWLEDGE_SOURCE_LABELS, source),
                by_name=str(payload.get("by_name") or ""),
                lines=lines,
            )
        )
    return KnowledgeHistoryOut(items=items)
