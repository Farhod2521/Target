"""The notice journal: one row per thing told, so nothing is told twice."""

from datetime import datetime

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.notifications.constants import (
    NOTICE_TRIES,
    NOTICES_WITHOUT_SUBSCRIPTION,
)
from app.modules.notifications.models import TelegramChat, TelegramNotice


def _row(
    db: Session, *, owner_id: object, kind: str, subject: str
) -> TelegramNotice | None:
    return db.scalars(
        select(TelegramNotice).where(
            TelegramNotice.owner_id == owner_id,
            TelegramNotice.kind == str(kind),
            TelegramNotice.subject == subject,
        )
    ).first()


def claim(
    db: Session, *, chat: TelegramChat, kind: str, subject: str
) -> TelegramNotice | None:
    """The row to send under, or None when it was sent or tried enough."""
    from app.modules.billing.selectors import has_live_subscription

    if kind not in NOTICES_WITHOUT_SUBSCRIPTION and not has_live_subscription(
        db, owner=chat.owner
    ):
        return None
    if _row(db, owner_id=chat.owner_id, kind=kind, subject=subject) is not None:
        return _next_try(db, owner=chat.owner, kind=kind, subject=subject)
    row = TelegramNotice(
        owner_id=chat.owner_id,
        chat_id=chat.id,
        kind=str(kind),
        subject=subject,
        attempts=1,
    )
    try:
        with db.begin_nested():
            db.add(row)
    except IntegrityError:
        return _next_try(db, owner=chat.owner, kind=kind, subject=subject)
    return row


def _next_try(
    db: Session, *, owner: User, kind: str, subject: str
) -> TelegramNotice | None:
    row = _row(db, owner_id=owner.id, kind=kind, subject=subject)
    if row is None or row.sent_at is not None or row.attempts >= NOTICE_TRIES:
        return None
    taken = db.execute(
        update(TelegramNotice)
        .where(TelegramNotice.id == row.id, TelegramNotice.attempts == row.attempts)
        .values(attempts=row.attempts + 1, updated_at=utcnow())
        .execution_options(synchronize_session=False)
    ).rowcount
    if not taken:
        return None
    db.refresh(row)
    return row


def settle(
    db: Session, *, chat: TelegramChat, kind: str, subject: str, now: datetime
) -> None:
    """Write a notice as already told, so a fresh link does not replay history."""
    try:
        with db.begin_nested():
            db.add(
                TelegramNotice(
                    owner_id=chat.owner_id,
                    chat_id=chat.id,
                    kind=str(kind),
                    subject=subject,
                    attempts=NOTICE_TRIES,
                    sent_at=now,
                )
            )
    except IntegrityError:
        return


def stamp(
    db: Session, *, notice: TelegramNotice, message_id: int, now: datetime
) -> None:
    if not message_id:
        return
    notice.message_id = message_id
    notice.sent_at = now
    db.flush()


__all__ = ["claim", "settle", "stamp"]
