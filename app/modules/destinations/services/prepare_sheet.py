"""Getting a link's files ready after a connection, a pick, or a lost file."""

import logging
import uuid

from googlekit import GoogleError, SheetsClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.cache import cache
from app.common.db import utcnow
from app.common.i18n import override
from app.modules.destinations.constants import (
    FILE_ACTIONS,
    PREPARE_LOCK_SECONDS,
    BrokenReason,
    SheetMode,
    SheetStatus,
)
from app.modules.destinations.models import SheetLink
from app.modules.destinations.services.access import open_sheets
from app.modules.destinations.services.prepare_modes import (
    prepare_own_file,
    prepare_per_form,
    prepare_single,
)
from app.modules.destinations.services.queue import queue_delivery
from app.modules.destinations.services.record import (
    close_actions,
    fail_actions,
    refuse_actions,
)
from app.modules.destinations.services.sheet_state import (
    activate,
    mark_broken,
    needs_person,
    settle,
)

logger = logging.getLogger(__name__)


def prepare_sheet(db: Session, *, link_id: str) -> str:
    """Give a link that is being prepared its files, then start sending.

    A link no longer preparing is left alone, and a lock keeps the sweep's
    copy of this task from making a second file while the first is at Google.
    """
    link = _preparing(db, link_id)
    if link is None:
        return "gone"
    key = f"destinations:prepare:{link.id}"
    if not cache.add(key, "1", PREPARE_LOCK_SECONDS):
        return "busy"
    try:
        return _prepare(db, link)
    finally:
        cache.delete(key)


def _preparing(db: Session, link_id: str) -> SheetLink | None:
    try:
        key = uuid.UUID(str(link_id))
    except ValueError:
        return None
    return db.scalar(
        select(SheetLink).where(
            SheetLink.id == key, SheetLink.status == SheetStatus.PREPARING
        ),
        execution_options={"populate_existing": True},
    )


def _prepare(db: Session, link: SheetLink) -> str:
    """Ready the files, answer the press that asked, then open the link.

    The press is answered as soon as the files are ready, whatever happens
    next; a link disconnected meanwhile keeps its file recorded and sends
    nothing to it.
    """
    now = utcnow()
    try:
        with open_sheets(link=link) as client, override(link.owner.language):
            outcome = _ready(db, link=link, client=client)
    except GoogleError as exc:
        if needs_person(exc):
            fail_actions(db, link=link, actions=FILE_ACTIONS, error=exc, now=now)
        return settle(db, link=link, error=exc, now=now)
    if isinstance(outcome, BrokenReason):
        refuse_actions(db, link=link, actions=FILE_ACTIONS, code=outcome, now=now)
        stopped = mark_broken(db, link=link, reason=outcome, now=now)
        return f"broken:{outcome}" if stopped else "moved"
    close_actions(db, link=link, actions=FILE_ACTIONS, now=now)
    if not activate(db, link=link, now=now):
        return "moved"
    queue_delivery(link_id=str(link.id))
    logger.info("sheet ready: owner=%s mode=%s %s", link.owner_id, link.mode, outcome)
    return outcome


def _ready(db: Session, *, link: SheetLink, client: SheetsClient) -> str | BrokenReason:
    if link.mode == SheetMode.OWN_FILE:
        return prepare_own_file(db, link=link, client=client)
    if link.mode == SheetMode.PER_FORM:
        return prepare_per_form(db, link=link, client=client)
    return prepare_single(db, link=link, client=client)


__all__ = ["prepare_sheet"]
