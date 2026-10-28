"""Which leads still have to reach the spreadsheet, and which are unconfirmed."""

from datetime import datetime, timedelta

from sqlalchemy import ColumnElement, Select, exists, func, select
from sqlalchemy.orm import Session, joinedload

from app.modules.destinations.constants import (
    RECENT_WINDOW_HOURS,
    Channel,
    DeliveryStatus,
)
from app.modules.destinations.models import LeadDelivery, SheetLink
from app.modules.leads.models import Lead
from app.modules.leads.selectors import owned


def _pending(*, link: SheetLink, now: datetime) -> Select[Lead]:
    """The owner's leads with no delivery row for the spreadsheet, oldest first.

    An anti-join, not a cursor; from ``deliver_from`` on, the one form's only
    when one was chosen, and only the last day once a pass found nothing left.
    """
    delivered = exists().where(
        LeadDelivery.lead_id == Lead.id, LeadDelivery.channel == Channel.SHEETS
    )
    query = (
        select(Lead)
        .where(owned(link.owner_id), Lead.anonymized_at.is_(None), ~delivered)
        .order_by(Lead.submitted_at, Lead.id)
    )
    if link.deliver_from is not None:
        query = query.where(Lead.created_at >= link.deliver_from)
    if link.only_form_id is not None:
        query = query.where(Lead.form_id == link.only_form_id)
    if link.caught_up_at is not None:
        query = query.where(
            Lead.created_at >= now - timedelta(hours=RECENT_WINDOW_HOURS)
        )
    return query


def pending_leads(
    db: Session, *, link: SheetLink, now: datetime, limit: int
) -> list[Lead]:
    return list(
        db.scalars(
            _pending(link=link, now=now).options(joinedload(Lead.form)).limit(limit)
        )
    )


def _sending(link: SheetLink) -> tuple[ColumnElement[bool], ...]:
    return (
        LeadDelivery.owner_id == link.owner_id,
        LeadDelivery.channel == Channel.SHEETS,
        LeadDelivery.status == DeliveryStatus.SENDING,
    )


def sending_by_file(
    db: Session, *, link: SheetLink
) -> dict[str | None, frozenset[str]]:
    """Leads sent and not yet confirmed, by the per-form file they went to.

    The key is the ``FormSheet`` id as a string, and ``None`` for the one file
    of the other ways of writing.
    """
    rows = db.execute(
        select(LeadDelivery.form_sheet_id, LeadDelivery.lead_id).where(*_sending(link))
    )
    grouped: dict[str | None, set[str]] = {}
    for form_sheet_id, lead_id in rows:
        key = str(form_sheet_id) if form_sheet_id is not None else None
        grouped.setdefault(key, set()).add(str(lead_id))
    return {key: frozenset(ids) for key, ids in grouped.items()}


def delivered_count(db: Session, *, link: SheetLink) -> int:
    """How many leads the file the link points at holds from this product."""
    return int(
        db.scalar(
            select(func.count())
            .select_from(LeadDelivery)
            .where(
                LeadDelivery.owner_id == link.owner_id,
                LeadDelivery.channel == Channel.SHEETS,
                LeadDelivery.status == DeliveryStatus.DELIVERED,
            )
        )
        or 0
    )


def has_work(db: Session, *, link: SheetLink, now: datetime) -> bool:
    """Whether a run for this link would do anything at all."""
    if link.caught_up_at is None:
        return True
    unconfirmed = db.scalar(select(exists().where(*_sending(link))))
    if unconfirmed:
        return True
    pending = _pending(link=link, now=now).order_by(None).limit(1).exists()
    return bool(db.scalar(select(pending)))


__all__ = ["delivered_count", "has_work", "pending_leads", "sending_by_file"]
