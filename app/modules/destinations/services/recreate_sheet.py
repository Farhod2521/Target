"""A new spreadsheet, after the old one was deleted or put in the bin."""

from datetime import timedelta
from functools import partial

from sqlalchemy.orm import Session

from app.common.db import on_commit, utcnow
from app.modules.accounts.models import User
from app.modules.audit.constants import ActionType, EventName
from app.modules.destinations.constants import (
    NEEDS_NEW_SHEET,
    PREPARE_GRACE_SECONDS,
    BrokenReason,
    SheetMode,
    SheetStatus,
)
from app.modules.destinations.exceptions import NoSheetLink, NothingToRecreate
from app.modules.destinations.models import SheetLink
from app.modules.destinations.selectors import locked_link_for
from app.modules.destinations.services.queue import queue_prepare
from app.modules.destinations.services.record import record_action


def recreate_sheet(db: Session, *, user: User) -> SheetLink:
    """Order a new file for a link whose file was lost.

    Only for that: a lost permission needs Google again. For a file of the
    owner's own, only a lost tab - the worker adds a tab of ours again.
    """
    link = locked_link_for(db, owner=user)
    if link is None or link.status == SheetStatus.DISCONNECTED:
        raise NoSheetLink
    if link.status != SheetStatus.BROKEN or link.broken_reason not in NEEDS_NEW_SHEET:
        raise NothingToRecreate
    own = link.mode == SheetMode.OWN_FILE
    if own and link.broken_reason != BrokenReason.TAB_GONE:
        raise NothingToRecreate
    now = utcnow()
    previous = {"status": link.status, "spreadsheet_id": link.spreadsheet_id}
    if not own:
        link.spreadsheet_id = ""
    link.sheet_id = ""
    link.spreadsheet_url = ""
    link.status = SheetStatus.PREPARING
    link.broken_reason = ""
    link.broken_at = None
    # What an attempt before the break was turned away with is no news about
    # the new file, and the screen would read it as a delay.
    link.last_error_code = ""
    link.next_attempt_at = now + timedelta(seconds=PREPARE_GRACE_SECONDS)
    db.flush()
    record_action(
        db,
        user=user,
        link=link,
        action=ActionType.SHEET_RECREATE,
        event=EventName.SHEET_RECREATED,
        previous=previous,
        now=now,
    )
    on_commit(db, partial(queue_prepare, link_id=str(link.id)))
    db.commit()
    return link


__all__ = ["recreate_sheet"]
