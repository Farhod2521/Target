"""The narrower kinds of business under a direction.

Nobody keeps the list by hand: a kind is made the first time a customer
names one that is not there. So the one rule that matters here is that the
same kind is not made twice. A name is levelled (case, apostrophes, spaces,
punctuation) before it is looked for or written, a kind is looked for under
its name and under every other word it is known by, and two kinds that turn
out to be one are merged, the name of the one given up becoming another word
for the one kept.
"""

import logging
import re
import uuid
from collections.abc import Iterable

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.businesses.constants import (
    SUBTYPE_NAME_CHARS,
    SUBTYPE_SYNONYMS,
    SubtypeOrigin,
)
from app.modules.businesses.exceptions import BadSubtype, SubtypeNameTaken
from app.modules.businesses.models import (
    BusinessCategory,
    BusinessKnowledge,
    BusinessSubtype,
)

logger = logging.getLogger(__name__)

_APOSTROPHES = re.compile(r"[’ʻ‘`´ʼ]")
_NOT_A_WORD = re.compile(r"[^\w']+", re.UNICODE)
# A whole merge chain is short; the bound only stops a loop made by hand.
_CHAIN = 10


def level(words: str) -> str:
    """The words as they are compared: «Oshxona  MEBELI!» and «oshxona
    mebeli» are one name."""
    plain = _APOSTROPHES.sub("'", str(words or "")).lower().replace("_", " ")
    return " ".join(_NOT_A_WORD.sub(" ", plain).split()).strip("' ")


def _named(words: str) -> tuple[str, str]:
    name = " ".join(str(words or "").split())
    key = level(name)
    if not key:
        raise BadSubtype("Yo'nalish nomini yozing.")
    if len(name) > SUBTYPE_NAME_CHARS or len(key) > SUBTYPE_NAME_CHARS:
        raise BadSubtype(f"Yo'nalish nomi {SUBTYPE_NAME_CHARS} belgidan oshmasin.")
    return name, key


def _other_words(words: Iterable[str], *, apart_from: str) -> list[str]:
    """The other names of a kind, each once, without the kind's own."""
    kept: list[str] = []
    seen = {apart_from}
    for word in words:
        plain = " ".join(str(word or "").split())[:SUBTYPE_NAME_CHARS]
        key = level(plain)
        if key and key not in seen:
            seen.add(key)
            kept.append(plain)
    return kept[:SUBTYPE_SYNONYMS]


def kept(db: Session, subtype: BusinessSubtype) -> BusinessSubtype:
    """The kind this one was merged into, or itself."""
    for _ in range(_CHAIN):
        if subtype.merged_into_id is None:
            return subtype
        target = db.get(BusinessSubtype, subtype.merged_into_id)
        if target is None:
            return subtype
        subtype = target
    return subtype


def find(
    db: Session, *, direction: BusinessCategory, words: str
) -> BusinessSubtype | None:
    """The kind a customer means by ``words``, under its name or under any
    other word for it; a merged one answers with the kind it became."""
    key = level(words)
    if not key:
        return None
    rows = list(
        db.scalars(
            select(BusinessSubtype)
            .where(BusinessSubtype.direction_id == direction.id)
            .order_by(BusinessSubtype.created_at, BusinessSubtype.id)
        )
    )
    for row in rows:
        if row.name_key == key:
            return kept(db, row)
    for row in rows:
        if row.merged_into_id is None and key in {
            level(word) for word in row.synonyms or []
        }:
            return row
    return None


def ensure(
    db: Session,
    *,
    direction: BusinessCategory,
    name: str,
    synonyms: Iterable[str] = (),
    origin: str = SubtypeOrigin.AI,
    actor: User | None = None,
) -> tuple[BusinessSubtype, bool]:
    """The kind of this name under the direction, made if it is not there.
    Answers the row and whether it was made now; flushes.

    One made by the assistant waits for the office to look at it
    (``is_checked`` false); one the office made is checked from the start.
    """
    shown, key = _named(name)
    found = find(db, direction=direction, words=shown)
    if found is not None:
        return found, False
    row = BusinessSubtype(
        direction_id=direction.id,
        name=shown,
        name_key=key,
        synonyms=_other_words(synonyms, apart_from=key),
        origin=str(origin),
        is_checked=str(origin) == SubtypeOrigin.STAFF,
        created_by_id=actor.id if actor is not None else None,
    )
    try:
        with db.begin_nested():
            db.add(row)
    except IntegrityError:
        # Made by another chat between the look and the write.
        found = find(db, direction=direction, words=shown)
        if found is None:
            raise
        return found, False
    logger.info("subtype %s made under %s by %s", key, direction.key, origin)
    return row, True


def change(
    db: Session,
    *,
    subtype: BusinessSubtype,
    name: str | None = None,
    synonyms: Iterable[str] | None = None,
    is_checked: bool | None = None,
    is_active: bool | None = None,
) -> BusinessSubtype:
    """An office edit of one kind; flushes."""
    if name is not None:
        shown, key = _named(name)
        if key != subtype.name_key:
            taken = db.scalar(
                select(BusinessSubtype.id).where(
                    BusinessSubtype.direction_id == subtype.direction_id,
                    BusinessSubtype.name_key == key,
                    BusinessSubtype.id != subtype.id,
                )
            )
            if taken is not None:
                raise SubtypeNameTaken
        subtype.name, subtype.name_key = shown, key
    if synonyms is not None or name is not None:
        words = synonyms if synonyms is not None else subtype.synonyms or []
        subtype.synonyms = _other_words(words, apart_from=subtype.name_key)
    if is_checked is not None:
        subtype.is_checked = is_checked
    if is_active is not None:
        subtype.is_active = is_active
    db.flush()
    return subtype


def merge(
    db: Session, *, source: BusinessSubtype, target: BusinessSubtype
) -> BusinessSubtype:
    """Give ``source`` up for ``target``: the businesses standing on it move,
    its name becomes another word for the kind kept, and it is never offered
    again. Answers the kind kept; flushes."""
    target = kept(db, target)
    if source.id == target.id:
        raise BadSubtype("Yo'nalishni o'zi bilan birlashtirib bo'lmaydi.")
    if source.merged_into_id is not None:
        raise BadSubtype("Bu yo'nalish allaqachon boshqasiga birlashtirilgan.")
    if source.direction_id != target.direction_id:
        raise BadSubtype("Faqat bitta turdagi yo'nalishlar birlashtiriladi.")
    moved = [source.id, *_merged_into(db, source.id)]
    db.execute(
        update(BusinessKnowledge)
        .where(BusinessKnowledge.subtype_id.in_(moved))
        .values(subtype_id=target.id)
    )
    db.execute(
        update(BusinessSubtype)
        .where(BusinessSubtype.merged_into_id == source.id)
        .values(merged_into_id=target.id)
    )
    target.synonyms = _other_words(
        [*(target.synonyms or []), source.name, *(source.synonyms or [])],
        apart_from=target.name_key,
    )
    source.merged_into_id = target.id
    source.is_active = False
    db.flush()
    logger.info("subtype %s merged into %s", source.name_key, target.name_key)
    return target


def _merged_into(db: Session, subtype_id: uuid.UUID) -> list[uuid.UUID]:
    return list(
        db.scalars(
            select(BusinessSubtype.id).where(
                BusinessSubtype.merged_into_id == subtype_id
            )
        )
    )


__all__ = ["change", "ensure", "find", "kept", "level", "merge"]
