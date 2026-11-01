"""Payouts across every Hamyon, and the asks waiting for one.

The waiting asks are the only rows whose card number is ever decrypted: the
operator paying needs all sixteen digits, and nobody needs them once it is paid.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import ColumnElement, func, or_, select, true
from sqlalchemy.orm import Session, joinedload

from app.common.crypto import decrypt
from app.modules.accounts.models import User
from app.modules.backoffice.constants import PAGE_SIZE, WITHDRAWAL_OVERDUE_HOURS
from app.modules.backoffice.selectors.payments import by_owner
from app.modules.referrals.constants import PayoutStatus
from app.modules.referrals.models import WithdrawalRequest

CARD_GROUP = 4
ANSWERED = (PayoutStatus.PAID, PayoutStatus.REJECTED, PayoutStatus.VOIDED)
PAYOUT_STATES: tuple[tuple[str, str], ...] = (
    ("", "Hammasi"),
    (PayoutStatus.PAID, "To'langan"),
    (PayoutStatus.REJECTED, "Rad etilgan"),
    (PayoutStatus.VOIDED, "Bekor qilingan"),
)


@dataclass(frozen=True, slots=True)
class PayoutPage:
    rows: tuple[WithdrawalRequest, ...]
    total: int
    offset: int
    counts: dict[str, int]

    @property
    def next_offset(self) -> int:
        return self.offset + len(self.rows)

    @property
    def has_more(self) -> bool:
        return self.next_offset < self.total


def _term(term: str) -> ColumnElement[bool]:
    if not term:
        return true()
    like = f"%{term}%"
    return or_(
        WithdrawalRequest.pay_reference.ilike(like),
        WithdrawalRequest.note.ilike(like),
        WithdrawalRequest.card_last4.ilike(like),
        *by_owner(term),
    )


def payout_page(
    db: Session, *, state: str = "", term: str = "", offset: int = 0
) -> PayoutPage:
    """Answered payouts, newest first. Voided rows stay: a history that hid them
    would disagree with what the earner was told. Each chip counts its state
    inside the search, and an ask still waiting is the queue's, not history."""
    found = (WithdrawalRequest.status.in_(ANSWERED), _term(term))
    counts = {
        str(status): int(total)
        for status, total in db.execute(
            select(WithdrawalRequest.status, func.count(WithdrawalRequest.id))
            .join(User, WithdrawalRequest.owner_id == User.id)
            .where(*found)
            .group_by(WithdrawalRequest.status)
        )
    }
    shown = (*found, WithdrawalRequest.status == state) if state else found
    rows = db.scalars(
        select(WithdrawalRequest)
        .join(User, WithdrawalRequest.owner_id == User.id)
        .options(
            joinedload(WithdrawalRequest.owner),
            joinedload(WithdrawalRequest.decided_by),
            joinedload(WithdrawalRequest.voided_by),
        )
        .where(*shown)
        .order_by(WithdrawalRequest.created_at.desc(), WithdrawalRequest.id)
        .offset(offset)
        .limit(PAGE_SIZE)
    )
    return PayoutPage(
        rows=tuple(rows),
        total=counts.get(state, 0) if state else sum(counts.values()),
        offset=offset,
        counts=counts,
    )


def payout_by_id(db: Session, *, payout_id: uuid.UUID) -> WithdrawalRequest | None:
    return db.get(WithdrawalRequest, payout_id)


def waiting_asks(db: Session) -> list[WithdrawalRequest]:
    """Every ask still waiting, the one waiting longest first. An earner holds
    one open ask at most, so the queue is as long as the earners waiting."""
    return list(
        db.scalars(
            select(WithdrawalRequest)
            .options(joinedload(WithdrawalRequest.owner))
            .where(WithdrawalRequest.status == PayoutStatus.REQUESTED)
            .order_by(WithdrawalRequest.created_at, WithdrawalRequest.id)
        )
    )


def is_overdue(ask: WithdrawalRequest, *, now: datetime) -> bool:
    return ask.created_at <= now - timedelta(hours=WITHDRAWAL_OVERDUE_HOURS)


def card_number(ask: WithdrawalRequest) -> str:
    """The whole card of a waiting ask, in fours as the bank's form takes it.

    An answered ask keeps its encrypted number as evidence: no screen reads it.
    """
    if ask.status != PayoutStatus.REQUESTED or not ask.card_number_encrypted:
        return ""
    digits = decrypt(bytes(ask.card_number_encrypted))
    return " ".join(
        digits[start : start + CARD_GROUP]
        for start in range(0, len(digits), CARD_GROUP)
    )
