"""The kept answers to refusals, as the office reads them."""

import uuid
from dataclasses import dataclass
from typing import Any, Final

from sqlalchemy import ColumnElement, Select, and_, func, or_, select
from sqlalchemy.orm import Session

from app.modules.backoffice.constants import PAGE_SIZE
from app.modules.chat.constants import (
    REFUSAL_ANSWER_FIELDS,
    REFUSAL_OPERATION_LABELS,
    REFUSAL_STALE_VERSIONS,
)
from app.modules.chat.models import RefusalAnswer

REVIEW: Final = "review"
RETIRED: Final = "retired"
TABS: Final[tuple[tuple[str, str], ...]] = (
    ("", "Hammasi"),
    (REVIEW, "Tekshirish kerak"),
    (RETIRED, "Eski javoblar"),
)
# The names an answer may write in double square brackets.
LINK_NAMES: Final[tuple[tuple[str, str], ...]] = (
    ("ulanish", "Ulanishlar sahifasi"),
    ("tolov", "Meta to'lov sahifasi"),
    ("ads_manager", "Ads Manager"),
    ("akkaunt_sifati", "Meta Account Quality"),
    ("reklama", "Reklama sahifasi (faqat reklama yaratish xatolarida)"),
    ("reja", "Reklama sozlamalari (faqat reklama yaratish xatolarida)"),
    ("media", "Rasm va video (faqat reklama yaratish xatolarida)"),
    ("forma", "Forma (faqat reklama yaratish xatolarida)"),
    ("lid_shartlari", "Meta lid shartlari (faqat reklama yaratish xatolarida)"),
    ("shaxs", "Meta shaxsni tasdiqlash (faqat reklama yaratish xatolarida)"),
)


@dataclass(frozen=True, slots=True)
class RefusalPage:
    rows: list[RefusalAnswer]
    total: int
    to_review: int
    offset: int
    next_offset: int
    has_more: bool


def _retired() -> ColumnElement[bool]:
    return RefusalAnswer.prompt_version.in_(list(REFUSAL_STALE_VERSIONS))


def _to_review() -> ColumnElement[bool]:
    """Claude's words no person has read: a text it adds clears ``edited_at``."""
    return and_(RefusalAnswer.edited_at.is_(None), ~_retired())


def _tab(query: Select[Any], tab: str) -> Select[Any]:
    if tab == REVIEW:
        return query.where(_to_review())
    if tab == RETIRED:
        return query.where(_retired())
    return query


def _search(query: Select[Any], term: str) -> Select[Any]:
    term = term.strip()
    if not term:
        return query
    like = f"%{term}%"
    return query.where(
        or_(
            RefusalAnswer.key.ilike(like),
            RefusalAnswer.provider_title.ilike(like),
            RefusalAnswer.provider_message.ilike(like),
            *(
                getattr(RefusalAnswer, field).ilike(like)
                for field in REFUSAL_ANSWER_FIELDS.values()
            ),
        )
    )


def refusal_answers(db: Session, *, tab: str, term: str, offset: int) -> RefusalPage:
    """The answers met most often first: those are worth correcting first."""
    query = _search(_tab(select(RefusalAnswer), tab), term)
    total = db.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = list(
        db.scalars(
            query.order_by(RefusalAnswer.hits.desc(), RefusalAnswer.created_at.desc())
            .offset(offset)
            .limit(PAGE_SIZE)
        )
    )
    to_review = db.scalar(
        select(func.count()).select_from(RefusalAnswer).where(_to_review())
    )
    next_offset = offset + len(rows)
    return RefusalPage(
        rows=rows,
        total=total,
        to_review=to_review or 0,
        offset=offset,
        next_offset=next_offset,
        has_more=next_offset < total,
    )


def refusal_answer(db: Session, *, answer_id: uuid.UUID) -> RefusalAnswer | None:
    return db.get(RefusalAnswer, answer_id)


def operation_of(key: str) -> str:
    """What the owner was doing, from the key's first word."""
    first = key.split(":", 1)[0]
    return first if first in REFUSAL_OPERATION_LABELS else "launch"


__all__ = [
    "LINK_NAMES",
    "TABS",
    "RefusalPage",
    "operation_of",
    "refusal_answer",
    "refusal_answers",
]
