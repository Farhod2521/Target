"""Taking a lead by the client's phone number: a Sales manager who talked a
client into buying on the phone makes that client theirs, whoever the
client is: kinds, the order of «Lid olish» and its limit do not apply.

- A lead nobody works (Ishlanmagan, closed, or no card yet) becomes the
  manager's, in Yangi lead.
- A lead another manager works is refused («Bu lid boshqa menejerda»), one
  the manager works already too («Bu lid sizda»).
- A client who paid a full plan before anybody took them may be claimed for
  ``PHONE_CLAIM_HOURS`` after the payment: the card stays in Sotildi and the
  sale is the manager's. Later, or nobody with the number: «Bunday lid yo'q».
"""

import re
from datetime import datetime, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.modules.accounts.exceptions import BadPhone
from app.modules.accounts.models import User
from app.modules.accounts.phone import clean_phone
from app.modules.billing.constants import InvoiceKind, InvoiceStatus
from app.modules.billing.models import Invoice
from app.modules.boards.constants import (
    PHONE_CLAIM_HOURS,
    TAKEN_BY_PHONE,
    Board,
    EventKind,
    SalesColumn,
)
from app.modules.boards.exceptions import LeadIsYours, LeadWithOther, NoSuchLead
from app.modules.boards.models import BoardCard
from app.modules.boards.services import move, record

# Fewer digits than this match too many numbers.
PHONE_MIN_DIGITS = 9
TAKEN_NOTE = "Raqam bilan olindi"


def client_by_phone(db: Session, raw: str) -> User | None:
    """The client signed up with this number; the latest sign-up when two
    share it. The number may be written any way: +998 90 123-45-67, or its
    last nine digits."""
    digits = re.sub(r"\D", "", raw)
    if len(digits) < PHONE_MIN_DIGITS:
        return None
    try:
        e164 = clean_phone(raw)
    except BadPhone:
        e164 = ""
    stored = func.regexp_replace(User.phone, r"\D", "", "g")
    return db.scalar(
        select(User)
        .where(
            User.is_staff.is_(False),
            User.is_superuser.is_(False),
            User.is_active.is_(True),
            User.crm_owner_id.is_(None),
            or_(User.phone == e164, stored.like(f"%{digits}")),
        )
        .order_by(User.date_joined.desc(), User.id)
        .limit(1)
    )


def _full_plan_paid_at(db: Session, client: User) -> datetime | None:
    from app.modules.boards.triggers import _full_plans

    return db.scalar(
        select(func.min(Invoice.paid_at)).where(
            Invoice.owner_id == client.id,
            Invoice.kind == str(InvoiceKind.PLAN),
            Invoice.status.in_([str(InvoiceStatus.PAID), str(InvoiceStatus.REFUNDED)]),
            Invoice.plan_id.in_(_full_plans()),
        )
    )


def _card(db: Session, client: User) -> BoardCard | None:
    return db.scalar(
        select(BoardCard)
        .where(BoardCard.board == str(Board.SALES), BoardCard.owner_id == client.id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )


def _new_card(
    db: Session, client: User, *, column: str, at: datetime, now: datetime
) -> BoardCard | None:
    """A card for a client the sweep never carded; None when the sweep made
    one this very moment (read it again)."""
    card = BoardCard(
        board=str(Board.SALES),
        owner_id=client.id,
        column_code=column,
        opened_at=at,
        column_since=now,
        reasons=[],
    )
    try:
        with db.begin_nested():
            db.add(card)
            db.flush()
    except IntegrityError:
        return None
    record(db, card=card, kind=EventKind.ADDED, now=now, to_column=column, ref="opened")
    return card


def take_by_phone(
    db: Session, *, manager: User, phone: str, now: datetime
) -> BoardCard:
    client = client_by_phone(db, phone)
    if client is None:
        raise NoSuchLead
    paid_at = _full_plan_paid_at(db, client)
    if paid_at is not None and now - paid_at > timedelta(hours=PHONE_CLAIM_HOURS):
        raise NoSuchLead
    card = _card(db, client)
    if card is None:
        column = str(SalesColumn.SOLD if paid_at else SalesColumn.UNWORKED)
        card = _new_card(db, client, column=column, at=paid_at or now, now=now)
        if card is None:
            card = _card(db, client)
        assert card is not None
        if paid_at is not None and card.column_code == SalesColumn.SOLD:
            card.closed_at = card.closed_at or paid_at
            record(db, card=card, kind=EventKind.SOLD, now=now, ref="sold")
    if paid_at is not None:
        return _claim_sale(db, card=card, manager=manager, now=now)
    if card.closed_at is None and card.manager_id is not None:
        raise LeadIsYours if card.manager_id == manager.id else LeadWithOther
    if card.column_code == SalesColumn.SOLD:
        # A plan the office gave: a client, not a lead.
        raise NoSuchLead
    card.closed_at = None
    card.close_reason = ""
    card.close_note = ""
    card.manager_id = manager.id
    card.due_at = None
    card.taken_as = TAKEN_BY_PHONE
    move(
        db,
        card=card,
        to=str(SalesColumn.NEW_LEAD),
        kind=EventKind.TAKEN,
        now=now,
        actor=manager,
        body=TAKEN_NOTE,
    )
    db.commit()
    return card


def _claim_sale(
    db: Session, *, card: BoardCard, manager: User, now: datetime
) -> BoardCard:
    """The client paid before anybody took them: the card keeps its place
    (Sotildi, or the next minute's sweep puts it there) and its sale becomes
    this manager's."""
    if card.manager_id is not None:
        raise LeadIsYours if card.manager_id == manager.id else LeadWithOther
    card.manager_id = manager.id
    card.taken_as = TAKEN_BY_PHONE
    record(db, card=card, kind=EventKind.TAKEN, now=now, actor=manager, body=TAKEN_NOTE)
    db.commit()
    return card
