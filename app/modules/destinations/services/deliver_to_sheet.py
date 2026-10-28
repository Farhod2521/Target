"""Copying new leads into the owner's spreadsheet."""

import logging
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from googlekit import GoogleError, SheetsClient
from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.common.cache import cache
from app.common.db import utcnow
from app.common.i18n import override
from app.modules.businesses.selectors import business_timezone
from app.modules.destinations.constants import (
    DELIVERY_BATCH,
    DELIVERY_BATCHES_PER_RUN,
    DELIVERY_LOCK_SECONDS,
    SheetMode,
    SheetStatus,
)
from app.modules.destinations.models import SheetLink
from app.modules.destinations.selectors import (
    form_sheets_for,
    pending_leads,
    sending_by_file,
)
from app.modules.destinations.services.access import open_sheets
from app.modules.destinations.services.deliver_per_form import send_per_form
from app.modules.destinations.services.sheet_state import (
    confirm,
    forget,
    mark_caught_up,
    mark_delivered,
    settle,
)
from app.modules.destinations.services.write_rows import Target, send_rows, tab_of

logger = logging.getLogger(__name__)


def deliver_to_sheet(db: Session, *, link_id: str) -> str:
    """One run for one link: settle what is unconfirmed, then send what is new.

    Locked per link, so two runs never pick the same pending leads.
    """
    link = _active(db, link_id)
    if link is None:
        return "gone"
    key = f"destinations:deliver:{link.id}"
    if not cache.add(key, "1", DELIVERY_LOCK_SECONDS):
        return "busy"
    try:
        return _run(db, link)
    finally:
        cache.delete(key)


def _active(db: Session, link_id: str) -> SheetLink | None:
    try:
        key = uuid.UUID(str(link_id))
    except ValueError:
        return None
    return db.scalar(
        select(SheetLink).where(
            SheetLink.id == key, SheetLink.status == SheetStatus.ACTIVE
        ),
        execution_options={"populate_existing": True},
    )


def _run(db: Session, link: SheetLink) -> str:
    """Refresh, reconcile, and send batches until caught up or out of turns."""
    now = utcnow()
    zone = _zone(db, link)
    sent = 0
    try:
        with open_sheets(link=link) as client, override(link.owner.language):
            _reconcile(db, link=link, client=client, now=now)
            for _turn in range(DELIVERY_BATCHES_PER_RUN):
                if not _still_as_read(db, link):
                    return "moved"
                count = _send_batch(db, link=link, client=client, zone=zone, now=now)
                sent += count
                if count < DELIVERY_BATCH:
                    mark_caught_up(db, link=link, now=now)
                    break
    except GoogleError as exc:
        return settle(db, link=link, error=exc, now=now)
    return f"sent:{sent}"


def _still_as_read(db: Session, link: SheetLink) -> bool:
    """Whether the link still writes where and from when this run read it.

    Asked before every batch: another way of writing chosen meanwhile forgets
    the old file and every delivery to it.
    """
    same_form = (
        SheetLink.only_form_id.is_(None)
        if link.only_form_id is None
        else SheetLink.only_form_id == link.only_form_id
    )
    same_start = (
        SheetLink.deliver_from.is_(None)
        if link.deliver_from is None
        else SheetLink.deliver_from == link.deliver_from
    )
    return bool(
        db.scalar(
            select(
                exists().where(
                    SheetLink.id == link.id,
                    SheetLink.status == SheetStatus.ACTIVE,
                    SheetLink.mode == link.mode,
                    same_form,
                    SheetLink.spreadsheet_id == link.spreadsheet_id,
                    same_start,
                )
            )
        )
    )


def _reconcile(
    db: Session, *, link: SheetLink, client: SheetsClient, now: datetime
) -> None:
    """Settle the rows a previous run sent without hearing back.

    The hidden first column holds each row's lead id: kept ones are
    confirmed, the rest go out again. Rows whose file is no longer recorded
    are simply sent again.
    """
    by_file = sending_by_file(db, link=link)
    if not by_file:
        return
    targets = _targets(db, link=link, keys=by_file)
    for key, unconfirmed in by_file.items():
        target = targets.get(key)
        if target is None or not target.spreadsheet_id:
            forget(db, link=link, lead_ids=unconfirmed)
            continue
        column = client.first_column(
            spreadsheet_id=target.spreadsheet_id, sheet_id=tab_of(target)
        )
        arrived = unconfirmed & frozenset(column)
        confirm(db, link=link, lead_ids=arrived, now=now)
        forget(db, link=link, lead_ids=unconfirmed - arrived)
        logger.info(
            "sheet reconciled: owner=%s arrived=%s resent=%s",
            link.owner_id,
            len(arrived),
            len(unconfirmed - arrived),
        )


def _targets(
    db: Session, *, link: SheetLink, keys: dict[str | None, frozenset[str]]
) -> dict[str | None, Target]:
    targets: dict[str | None, Target] = {None: link}
    if any(key is not None for key in keys):
        targets.update(
            {str(sheet.id): sheet for sheet in form_sheets_for(db, link=link)}
        )
    return targets


def _send_batch(
    db: Session,
    *,
    link: SheetLink,
    client: SheetsClient,
    zone: ZoneInfo | None,
    now: datetime,
) -> int:
    """Append the next batch of pending leads. Returns how many went."""
    leads = pending_leads(db, link=link, now=now, limit=DELIVERY_BATCH)
    if not leads:
        return 0
    if link.mode == SheetMode.PER_FORM:
        send_per_form(db, link=link, client=client, leads=leads, zone=zone, now=now)
    else:
        send_rows(
            db,
            link=link,
            client=client,
            target=link,
            leads=leads,
            zone=zone,
            now=now,
        )
    mark_delivered(db, link=link, now=now)
    return len(leads)


def _zone(db: Session, link: SheetLink) -> ZoneInfo | None:
    """The owner's zone, or ``None`` for UTC when none is set or it is unknown."""
    name = business_timezone(db, owner=link.owner)
    if not name:
        return None
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        logger.warning("unknown business timezone: owner=%s", link.owner_id)
        return None


__all__ = ["deliver_to_sheet"]
