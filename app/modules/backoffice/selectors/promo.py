"""Promo codes, and the requests waiting for an answer.

Two reads for one screen. The codes are a catalogue an operator maintains;
the queue is work, and it is the half that has a deadline - a request holds
one of the offer's uses while it waits, so an unread queue quietly oversells
the campaign it belongs to.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import ColumnElement, Select, func, or_, select, true
from sqlalchemy.orm import Session, joinedload

from app.modules.accounts.models import User
from app.modules.billing.constants import HELD_REDEMPTION_STATUSES, RedemptionStatus
from app.modules.billing.models import PromoCode, PromoRedemption
from app.modules.billing.selectors.promo import counted_redemptions

REQUESTS_PAGE = 20
ANSWERED_TAB = "answered"
# The states in which a code can still be typed today, or will be soon. The
# rest are history and fold away on the screen.
CURRENT_STATUSES = ("live", "scheduled")
STATUS_LABELS = {
    "live": "Ishlayapti",
    "scheduled": "Rejalashtirilgan",
    "spent": "Limit tugagan",
    "expired": "Muddati tugagan",
    "off": "O'chiq",
}


@dataclass(frozen=True, slots=True)
class CodeRow:
    """One offer, how much of it is left, and what state it is in."""

    code: PromoCode
    used: int
    percent: int
    status: str


@dataclass(frozen=True, slots=True)
class Catalogue:
    current: tuple[CodeRow, ...]
    finished: tuple[CodeRow, ...]


@dataclass(frozen=True, slots=True)
class RequestRow:
    """One request, with the one fact that changes the answer: how often
    this person has been refused before."""

    redemption: PromoRedemption
    refused_before: int


@dataclass(frozen=True, slots=True)
class RequestPage:
    rows: tuple[RequestRow, ...]
    total: int
    offset: int

    @property
    def next_offset(self) -> int:
        return self.offset + len(self.rows)

    @property
    def has_more(self) -> bool:
        return self.next_offset < self.total


def catalogue(db: Session, *, now: datetime) -> Catalogue:
    """Every code, live ones first, the current kept apart from the finished."""
    codes = db.scalars(
        select(PromoCode)
        .options(joinedload(PromoCode.plan))
        .order_by(PromoCode.is_active.desc(), PromoCode.created_at.desc())
    )
    counts = _usage(db)
    rows = [
        CodeRow(
            code=code,
            used=counts.get(code.id, 0),
            percent=fill_percent(counts.get(code.id, 0), code.max_uses),
            status=status_of(code=code, used=counts.get(code.id, 0), now=now),
        )
        for code in codes
    ]
    return Catalogue(
        current=tuple(row for row in rows if row.status in CURRENT_STATUSES),
        finished=tuple(row for row in rows if row.status not in CURRENT_STATUSES),
    )


def status_of(*, code: PromoCode, used: int, now: datetime) -> str:
    """Off, expired, spent, scheduled or live. Switched off wins over
    everything - it is the only state a person chose on purpose."""
    if not code.is_active:
        return "off"
    if code.expires_at is not None and code.expires_at <= now:
        return "expired"
    if code.max_uses and used >= code.max_uses:
        return "spent"
    if code.starts_at is not None and code.starts_at > now:
        return "scheduled"
    return "live"


def _usage(db: Session) -> dict[uuid.UUID, int]:
    """Uses each code has spent; a waiting request still spends one, the
    rule ``times_used`` applies to a single code."""
    held = (
        counted_redemptions()
        .where(PromoRedemption.status.in_(HELD_REDEMPTION_STATUSES))
        .subquery()
    )
    rows = db.execute(select(held.c.promo_id, func.count()).group_by(held.c.promo_id))
    return {promo_id: int(total) for promo_id, total in rows}


def fill_percent(used: int, allowed: int) -> int:
    """How full the offer is. Zero allowed means no ceiling, so no bar."""
    if allowed <= 0:
        return 0
    return min(round(used * 100 / allowed), 100)


def _by_term(term: str) -> ColumnElement[bool]:
    """Part of a name, an email, or a code; nothing typed narrows nothing."""
    if not term:
        return true()
    like = f"%{term}%"
    people = select(User.id).where(
        or_(User.email.ilike(like), User.full_name.ilike(like))
    )
    codes = select(PromoCode.id).where(PromoCode.code.ilike(like))
    return or_(
        PromoRedemption.owner_id.in_(people), PromoRedemption.promo_id.in_(codes)
    )


def _waiting(term: str) -> Select[Any]:
    """Unanswered, oldest first: the person waiting two days is the one the
    queue exists for."""
    return (
        select(PromoRedemption)
        .where(PromoRedemption.status == RedemptionStatus.PENDING, _by_term(term))
        .order_by(PromoRedemption.redeemed_at)
    )


def _decided(term: str) -> Select[Any]:
    """Answers somebody actually gave, newest first. A discount taken at
    checkout is written approved with no decision moment, and would sort
    above every real answer."""
    return (
        select(PromoRedemption)
        .where(
            PromoRedemption.decided_at.is_not(None),
            PromoRedemption.status != RedemptionStatus.PENDING,
            _by_term(term),
        )
        .order_by(PromoRedemption.decided_at.desc())
    )


def requests(
    db: Session, *, answered: bool, term: str = "", offset: int = 0
) -> RequestPage:
    """One page of the queue, or of the answers already given."""
    query = _decided(term) if answered else _waiting(term)
    total = int(db.scalar(select(func.count()).select_from(query.subquery())) or 0)
    found = list(
        db.scalars(
            query.options(
                joinedload(PromoRedemption.owner),
                joinedload(PromoRedemption.promo).joinedload(PromoCode.plan),
                joinedload(PromoRedemption.decided_by),
            )
            .offset(offset)
            .limit(REQUESTS_PAGE)
        )
    )
    refusals = {} if answered else _refusals(db, [row.owner_id for row in found])
    return RequestPage(
        rows=tuple(
            RequestRow(redemption=row, refused_before=refusals.get(row.owner_id, 0))
            for row in found
        ),
        total=total,
        offset=offset,
    )


def _refusals(db: Session, owner_ids: list[uuid.UUID]) -> dict[uuid.UUID, int]:
    if not owner_ids:
        return {}
    rows = db.execute(
        select(PromoRedemption.owner_id, func.count())
        .where(
            PromoRedemption.owner_id.in_(owner_ids),
            PromoRedemption.status == RedemptionStatus.REJECTED,
        )
        .group_by(PromoRedemption.owner_id)
    )
    return {owner_id: int(total) for owner_id, total in rows}


def request_by_id(db: Session, *, request_id: uuid.UUID) -> PromoRedemption | None:
    """Not narrowed to pending: whether it may still be answered is the
    decision's question, and hiding an answered row would turn "somebody got
    there first" into "this never existed"."""
    return db.get(PromoRedemption, request_id)


def code_by_id(db: Session, *, code_id: uuid.UUID) -> PromoCode | None:
    return db.get(PromoCode, code_id)
