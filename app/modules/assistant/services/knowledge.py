"""What a person told the assistant about their business, on its way to
being kept.

The model only ever prepares: ``note_business`` hands over what the person
said, :func:`prepared_note` turns it into the small changes the business's
knowledge is changed by (``businesses.services.knowledge``), and
:func:`keep_note` puts them on the waiting list with a button under the
answer. They become knowledge when the person presses it (:func:`save`),
and leave the list when they say no (:func:`drop`).
"""

import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Final

from sqlalchemy.orm import Session

from app.common.exceptions import DomainError
from app.common.shown import shown
from app.modules.accounts.models import User
from app.modules.assistant.constants import ButtonKind, ButtonState
from app.modules.businesses.constants import (
    SUBTYPE_NAME_CHARS,
    ItemStatus,
    KnowledgeSource,
    TypeState,
)
from app.modules.businesses.exceptions import BadKnowledgeChange, UnknownProposal
from app.modules.businesses.models import Business, BusinessCategory
from app.modules.businesses.selectors import business_for, offered_directions
from app.modules.businesses.selectors.knowledge import Known, describe, known
from app.modules.businesses.services import knowledge, subtypes
from app.modules.businesses.services.kinds import set_kind
from app.modules.businesses.services.subtypes import level

logger = logging.getLogger(__name__)

NOTE_KEY: Final = "K"
SAVE_LABEL: Final = "Eslab qolish"
SAVED_WORDS: Final = "Saqlandi. Keyingi reklamalarda shundan foydalanamiz."
NOT_SAVED: Final = "Saqlab bo'lmadi."

NO_BUSINESS: Final = (
    "Not kept: this account has no business set up yet. Do not mention it; "
    "answer what they asked."
)
NOTHING_NEW: Final = (
    "Nothing new to keep: all of this is already in the Context's Business "
    "section. Do not mention it; answer what they asked."
)
ALREADY: Final = "A note is already prepared for this answer."
PREPARED: Final = (
    "Prepared, and nothing is saved yet. Under your answer the product "
    "shows what will be kept and the «Eslab qolish» button; it is kept only "
    "when they press it. Answer what they asked first; then say in one "
    "short sentence that you can remember this about their business for "
    "the next adverts. Do not list it again, do not mention a button's "
    "name, and never say it was saved. To be kept:\n{lines}"
)


@dataclass(frozen=True, slots=True)
class Note:
    """One answer's note: whose business, the changes, and how they read."""

    business_id: uuid.UUID | None = None
    business_name: str = ""
    changes: list[dict[str, Any]] = field(default_factory=list)
    lines: list[str] = field(default_factory=list)
    text: str = ""


def _said(arguments: Any, name: str) -> str:
    return " ".join(str(getattr(arguments, name, "") or "").split())


def _item_changes(view: Known, sold: Any) -> list[dict[str, Any]]:
    """One thing sold, against what is kept: nothing when it says nothing new."""
    name = _said(sold, "name")
    key = level(name)
    held = next(
        (one for one in view.items if level(str(one.get("name") or "")) == key), None
    )
    if getattr(sold, "gone", False):
        if held is None or held.get("status") != ItemStatus.ACTIVE:
            return []
        return [{"op": knowledge.ARCHIVE_ITEM, "id": held["id"]}]
    change: dict[str, Any] = {"op": knowledge.ADD_ITEM, "name": name}
    for part in ("price", "note"):
        words = _said(sold, part)
        if words and (held is None or words != str(held.get(part) or "")):
            change[part] = words
    kind = str(getattr(sold, "kind", "") or "")
    if held is None:
        if kind:
            change["kind"] = kind
        return [change]
    if held.get("status") != ItemStatus.ACTIVE or len(change) > 2:
        return [change]
    return []


def _changes(view: Known, arguments: Any) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []
    about = _said(arguments, "about")
    if about and about != str((view.about or {}).get("text") or ""):
        changes.append({"op": knowledge.SET_ABOUT, "text": about})
    for sold in getattr(arguments, "items", ()) or ():
        changes += _item_changes(view, sold)
    for fact in getattr(arguments, "facts", ()) or ():
        key, value = str(getattr(fact, "key", "")), _said(fact, "value")
        if value and value != str((view.facts.get(key) or {}).get("value") or ""):
            changes.append({"op": knowledge.SET_FACT, "key": key, "value": value})
    return changes


def prepared_note(db: Session, *, owner: User, arguments: Any) -> Note:
    """What the model handed over, as changes to this person's business.
    Nothing is written: ``text`` is what the model is told."""
    business = business_for(db, owner)
    if business is None:
        return Note(text=NO_BUSINESS)
    view = known(db, business)
    clean: list[dict[str, Any]] = []
    for change in _changes(view, arguments):
        try:
            clean.append(knowledge.checked(change))
        except BadKnowledgeChange:
            # One bad line does not lose the rest of what was said.
            logger.info("assistant_note_line_dropped", extra={"op": change.get("op")})
    if not clean:
        return Note(text=NOTHING_NEW)
    lines = [describe(change, items=view.items) for change in clean]
    return Note(
        business_id=business.id,
        business_name=business.name,
        changes=clean,
        lines=lines,
        text=PREPARED.format(lines="\n".join(f"- {line}" for line in lines)),
    )


def keep_note(
    db: Session,
    *,
    owner: User,
    note: Note,
    number: int,
    shown_in: str,
    now: datetime,
) -> dict[str, Any] | None:
    """Put a prepared note on the business's waiting list; flushes. Answers
    the button that goes under the answer, or nothing when the business is
    gone."""
    business = _business(db, owner=owner, pk=note.business_id)
    if business is None:
        return None
    proposal = knowledge.propose(
        db,
        business=business,
        changes=note.changes,
        source=KnowledgeSource.ASSISTANT,
        actor=owner,
        now=now,
    ) or _waiting(db, business=business, changes=note.changes)
    if proposal is None:
        return None
    return {
        "kind": ButtonKind.KNOWLEDGE,
        "key": f"{NOTE_KEY}{number}",
        "label": shown(SAVE_LABEL, shown_in),
        "state": ButtonState.OPEN,
        "target": note.business_name,
        "lines": note.lines,
        "business_id": str(business.id),
        "proposal_id": str(proposal["id"]),
    }


def _waiting(
    db: Session, *, business: Business, changes: list[dict[str, Any]]
) -> dict[str, Any] | None:
    """The very same changes, proposed before and still unanswered."""
    document = knowledge.document_of(knowledge.row_of(db, business))
    return next(
        (one for one in document["pending"] if one.get("changes") == changes), None
    )


def _business(db: Session, *, owner: User, pk: Any) -> Business | None:
    try:
        key = pk if isinstance(pk, uuid.UUID) else uuid.UUID(str(pk))
    except ValueError:
        return None
    business = db.get(Business, key)
    if business is None or business.user_id != owner.id:
        return None
    return business


def save(
    db: Session, *, owner: User, item: dict[str, Any], now: datetime
) -> tuple[str, str]:
    """The person pressed the button: ``(state, words)``; flushes."""
    business = _business(db, owner=owner, pk=item.get("business_id"))
    if business is None:
        return ButtonState.GONE, ""
    try:
        with db.begin_nested():
            knowledge.confirm(
                db,
                business=business,
                proposal_id=str(item.get("proposal_id", "")),
                actor=owner,
                now=now,
            )
    except UnknownProposal:
        return ButtonState.GONE, ""
    except DomainError as exc:
        return ButtonState.REFUSED, str(exc) or NOT_SAVED
    return ButtonState.DONE, SAVED_WORDS


def drop(db: Session, *, owner: User, item: dict[str, Any], now: datetime) -> None:
    """The person said no: the note leaves the waiting list; flushes."""
    business = _business(db, owner=owner, pk=item.get("business_id"))
    if business is None:
        return
    try:
        with db.begin_nested():
            knowledge.reject(
                db,
                business=business,
                proposal_id=str(item.get("proposal_id", "")),
                actor=owner,
                now=now,
            )
    except UnknownProposal:
        # Answered from the business's own page meanwhile.
        return


# -- the business's kind -------------------------------------------------------

KIND_KEY: Final = "B"
KIND_LABEL: Final = "Tasdiqlash"
KIND_SAVED: Final = "Saqlandi. Reklamalar shu yo'nalishga moslab tayyorlanadi."
BAD_DIRECTION: Final = (
    "Not prepared: '{key}' is not a kind's key. Use one key from the "
    "Context's 'Kinds to choose from' line, exactly as written."
)
SAME_KIND: Final = (
    "Nothing to confirm: the business already has exactly this kind and "
    "name, confirmed. Do not mention it; answer what they asked."
)
KIND_PREPARED: Final = (
    "Prepared, and nothing is saved yet. Under your answer the product "
    "shows this and a «Tasdiqlash» button; it is saved only when they "
    "press it. Say in one short sentence what you understood their "
    "business to be, in their language, and carry on. Do not mention a "
    "button's name and never say it was saved. To be confirmed:\n{lines}"
)


@dataclass(frozen=True, slots=True)
class KindNote:
    """One answer's prepared kind: whose business, and what is confirmed."""

    business_id: uuid.UUID | None = None
    business_name: str = ""
    direction_id: uuid.UUID | None = None
    subtype: str = ""
    name: str = ""
    lines: list[str] = field(default_factory=list)
    text: str = ""

    @property
    def ready(self) -> bool:
        return self.direction_id is not None


def kind_choices(db: Session) -> str:
    """The closed list of kinds as the Context names it: ``key - label``."""
    return "; ".join(f"{row.key} - {row.label_uz}" for row in offered_directions(db))


def prepared_kind(db: Session, *, owner: User, arguments: Any) -> KindNote:
    """What the model handed over, checked against the closed list. Nothing
    is written: ``text`` is what the model is told."""
    business = business_for(db, owner)
    if business is None:
        return KindNote(text=NO_BUSINESS)
    key = _said(arguments, "direction").lower()
    direction = next((row for row in offered_directions(db) if row.key == key), None)
    if direction is None:
        return KindNote(text=BAD_DIRECTION.format(key=key))
    subtype = _said(arguments, "subtype")[:SUBTYPE_NAME_CHARS]
    name = _said(arguments, "name")[:255]
    view = known(db, business)
    same_subtype = level(subtype) == level(view.subtype.name if view.subtype else "")
    if (
        view.type_state == TypeState.CONFIRMED
        and view.direction is not None
        and view.direction.id == direction.id
        and same_subtype
        and (not name or name == view.profile.name)
    ):
        return KindNote(text=SAME_KIND)
    kind = direction.label_uz + (f" → {subtype}" if subtype else "")
    lines = [f"Biznes turi: {kind}"]
    if name and name != view.profile.name:
        lines.append(f"Nomi: {name}")
    return KindNote(
        business_id=business.id,
        business_name=business.name,
        direction_id=direction.id,
        subtype=subtype,
        name=name,
        lines=lines,
        text=KIND_PREPARED.format(lines="\n".join(f"- {line}" for line in lines)),
    )


def kind_button(*, note: KindNote, number: int, shown_in: str) -> dict[str, Any]:
    """The button under the answer. Nothing is written until it is pressed."""
    return {
        "kind": ButtonKind.BUSINESS_KIND,
        "key": f"{KIND_KEY}{number}",
        "label": shown(KIND_LABEL, shown_in),
        "state": ButtonState.OPEN,
        "target": note.business_name,
        "lines": note.lines,
        "business_id": str(note.business_id),
        "direction_id": str(note.direction_id),
        "subtype": note.subtype,
        "name": note.name,
    }


def save_kind(
    db: Session, *, owner: User, item: dict[str, Any], now: datetime
) -> tuple[str, str]:
    """The person pressed the button: the kind is theirs now, confirmed;
    ``(state, words)``; flushes."""
    business = _business(db, owner=owner, pk=item.get("business_id"))
    if business is None:
        return ButtonState.GONE, ""
    try:
        direction = db.get(BusinessCategory, uuid.UUID(str(item.get("direction_id"))))
    except ValueError:
        direction = None
    if direction is None:
        return ButtonState.GONE, ""
    try:
        with db.begin_nested():
            subtype = None
            if str(item.get("subtype") or "").strip():
                subtype, _made = subtypes.ensure(
                    db,
                    direction=direction,
                    name=str(item["subtype"]),
                    actor=owner,
                )
            set_kind(
                db,
                business=business,
                direction=direction,
                subtype=subtype,
                state=TypeState.CONFIRMED,
                source=KnowledgeSource.ASSISTANT,
                actor=owner,
                now=now,
            )
            name = " ".join(str(item.get("name") or "").split())
            if name:
                profile = knowledge.home(db, business)
                for one in {profile.id: profile, business.id: business}.values():
                    one.name = name[:255]
                    one.updated_at = now
                db.flush()
    except DomainError as exc:
        return ButtonState.REFUSED, str(exc) or NOT_SAVED
    return ButtonState.DONE, KIND_SAVED


__all__ = [
    "ALREADY",
    "KIND_SAVED",
    "NOTE_KEY",
    "SAVED_WORDS",
    "KindNote",
    "Note",
    "drop",
    "keep_note",
    "kind_button",
    "kind_choices",
    "prepared_kind",
    "prepared_note",
    "save",
    "save_kind",
]
