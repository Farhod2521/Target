"""What a link and its delivery rows become after Google answers.

Every write here is small and commits on its own; none is wrapped around a
call to Google. A move - :func:`mark_broken`, :func:`activate`,
:func:`back_off` - touches only a row still as it was read, and says whether
it did: the owner may have pressed something while Google was answering.
A fact about the file - its address, what reached it - is written whatever.
"""

import logging
import uuid
from collections.abc import Iterable, Sequence
from datetime import datetime, timedelta

from googlekit import (
    AccessRevoked,
    GoogleAPIError,
    GoogleError,
    PermissionMissing,
    RateLimited,
    SheetMissing,
    Spreadsheet,
    TabMissing,
    Unavailable,
)
from sqlalchemy import ColumnElement, delete, update
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import set_committed_value

from app.modules.destinations.constants import (
    FIRST_TAB,
    OUTAGE_BACKOFF_SECONDS,
    RATE_LIMIT_BACKOFF_SECONDS,
    REFUSAL_BACKOFF_SECONDS,
    BrokenReason,
    Channel,
    DeliveryStatus,
    SheetStatus,
)
from app.modules.destinations.models import LeadDelivery, SheetLink

logger = logging.getLogger(__name__)


def settle(db: Session, *, link: SheetLink, error: GoogleError, now: datetime) -> str:
    """The one place a failure from Google becomes stored state.

    Three failures need a person and break the link; the rest only push the
    next attempt back. Returns a word for the task's log line.
    """
    reason = _broken_by(error)
    if reason is not None:
        stopped = mark_broken(db, link=link, reason=reason, now=now)
        return f"broken:{reason}" if stopped else "moved"
    if isinstance(error, GoogleAPIError):
        logger.error(
            "sheet request refused: owner=%s error=%s",
            link.owner_id,
            type(error).__name__,
        )
    if not back_off(db, link=link, error=error, now=now):
        return "moved"
    return f"backoff:{type(error).__name__}"


def needs_person(error: GoogleError) -> bool:
    """Whether ``error`` stops a link until somebody presses a button."""
    return _broken_by(error) is not None


def mark_broken(
    db: Session, *, link: SheetLink, reason: BrokenReason, now: datetime
) -> bool:
    """Stop the link until a person acts. Returns whether it did."""
    stopped = _move(
        db,
        link,
        status=SheetStatus.BROKEN,
        broken_reason=reason,
        broken_at=now,
        next_attempt_at=None,
        updated_at=now,
    )
    if stopped:
        logger.warning("sheet link broken: owner=%s reason=%s", link.owner_id, reason)
    return stopped


def back_off(
    db: Session, *, link: SheetLink, error: GoogleError, now: datetime
) -> bool:
    """Leave the link alone for a while. The sweep comes back after it."""
    return _move(
        db,
        link,
        next_attempt_at=now + timedelta(seconds=_backoff_seconds(error)),
        last_error_code=type(error).__name__,
        updated_at=now,
    )


def activate(db: Session, *, link: SheetLink, now: datetime) -> bool:
    """Back to sending - and a full pass first, whatever was missed meanwhile."""
    return _move(
        db,
        link,
        status=SheetStatus.ACTIVE,
        broken_reason="",
        broken_at=None,
        caught_up_at=None,
        next_attempt_at=None,
        last_error_code="",
        last_checked_at=now,
        updated_at=now,
    )


def adopt_sheet(db: Session, *, link: SheetLink, sheet: Spreadsheet) -> None:
    """Point the link at a new file, and forget every delivery to the old one.

    Both in one transaction: a new file beside the old file's records would
    stay empty for good.
    """
    _forget_deliveries(db, link=link)
    link.spreadsheet_id = sheet.spreadsheet_id
    link.sheet_id = sheet.sheet_ids[0] if sheet.sheet_ids else FIRST_TAB
    link.spreadsheet_url = sheet.url
    link.columns = []
    db.commit()


def begin_sending(
    db: Session,
    *,
    link: SheetLink,
    lead_ids: Sequence[str],
    now: datetime,
    form_sheet_id: str | None = None,
) -> None:
    """Write the unconfirmed records - committed before the rows leave."""
    db.add_all(
        LeadDelivery(
            owner_id=link.owner_id,
            lead_id=uuid.UUID(str(lead_id)),
            channel=Channel.SHEETS,
            form_sheet_id=uuid.UUID(form_sheet_id) if form_sheet_id else None,
            status=DeliveryStatus.SENDING,
            sent_at=now,
        )
        for lead_id in lead_ids
    )
    db.commit()


def confirm(
    db: Session, *, link: SheetLink, lead_ids: Iterable[str], now: datetime
) -> int:
    """The rows are in the spreadsheet."""
    result = db.execute(
        update(LeadDelivery)
        .where(*_unconfirmed(link=link, lead_ids=lead_ids))
        .values(status=DeliveryStatus.DELIVERED, delivered_at=now, updated_at=now)
        .execution_options(synchronize_session=False)
    )
    db.commit()
    return int(getattr(result, "rowcount", 0) or 0)


def forget(db: Session, *, link: SheetLink, lead_ids: Iterable[str]) -> int:
    """The rows are not in the spreadsheet, so these leads are pending again."""
    result = db.execute(
        delete(LeadDelivery)
        .where(*_unconfirmed(link=link, lead_ids=lead_ids))
        .execution_options(synchronize_session=False)
    )
    db.commit()
    return int(getattr(result, "rowcount", 0) or 0)


def mark_delivered(db: Session, *, link: SheetLink, now: datetime) -> None:
    link.last_delivered_at = now
    link.last_error_code = ""
    db.commit()


def mark_caught_up(db: Session, *, link: SheetLink, now: datetime) -> None:
    """A pass found nothing left, so later runs look only at recent leads."""
    link.caught_up_at = now
    db.commit()


def mark_checked(db: Session, *, link: SheetLink, now: datetime) -> None:
    link.last_checked_at = now
    db.commit()


def forget_token(db: Session, *, link: SheetLink, now: datetime) -> None:
    """Drop a disconnected link's secret - only if it is still the same one."""
    db.execute(
        update(SheetLink)
        .where(
            SheetLink.id == link.id,
            SheetLink.status == SheetStatus.DISCONNECTED,
            SheetLink.token_fingerprint == link.token_fingerprint,
        )
        .values(token_encrypted=b"", token_fingerprint="", updated_at=now)
        .execution_options(synchronize_session=False)
    )
    db.commit()


def _forget_deliveries(db: Session, *, link: SheetLink) -> None:
    db.execute(
        delete(LeadDelivery)
        .where(
            LeadDelivery.owner_id == link.owner_id,
            LeadDelivery.channel == Channel.SHEETS,
        )
        .execution_options(synchronize_session=False)
    )


def _move(db: Session, link: SheetLink, **fields: object) -> bool:
    """Write ``fields`` if the row is still as ``link`` was read, and say so.

    "As read" is the status and the reason together. On success ``link`` is
    brought up to date.
    """
    result = db.execute(
        update(SheetLink)
        .where(
            SheetLink.owner_id == link.owner_id,
            SheetLink.id == link.id,
            SheetLink.status == link.status,
            SheetLink.broken_reason == link.broken_reason,
        )
        .values(**fields)
        .execution_options(synchronize_session=False)
    )
    db.commit()
    if not getattr(result, "rowcount", 0):
        return False
    for name, value in fields.items():
        set_committed_value(link, name, value)
    return True


def _unconfirmed(
    *, link: SheetLink, lead_ids: Iterable[str]
) -> tuple[ColumnElement[bool], ...]:
    return (
        LeadDelivery.owner_id == link.owner_id,
        LeadDelivery.channel == Channel.SHEETS,
        LeadDelivery.status == DeliveryStatus.SENDING,
        LeadDelivery.lead_id.in_([uuid.UUID(str(value)) for value in lead_ids]),
    )


def _broken_by(error: GoogleError) -> BrokenReason | None:
    """The reason a failure breaks the link, or ``None`` if it passes."""
    if isinstance(error, AccessRevoked):
        return BrokenReason.REVOKED
    if isinstance(error, PermissionMissing):
        return BrokenReason.PERMISSION
    if isinstance(error, TabMissing):
        return BrokenReason.TAB_GONE
    if isinstance(error, SheetMissing):
        return BrokenReason.SHEET_GONE
    return None


def _backoff_seconds(error: GoogleError) -> int:
    if isinstance(error, RateLimited):
        return RATE_LIMIT_BACKOFF_SECONDS
    if isinstance(error, Unavailable):
        return OUTAGE_BACKOFF_SECONDS
    return REFUSAL_BACKOFF_SECONDS


__all__ = [
    "activate",
    "adopt_sheet",
    "back_off",
    "begin_sending",
    "confirm",
    "forget",
    "forget_token",
    "mark_broken",
    "mark_caught_up",
    "mark_checked",
    "mark_delivered",
    "needs_person",
    "settle",
]
