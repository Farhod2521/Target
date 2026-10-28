"""Stopping the spreadsheet, and handing Google its permission back."""

from functools import partial

from sqlalchemy.orm import Session

from app.common.cache import cache
from app.common.db import on_commit, utcnow
from app.modules.accounts.models import User
from app.modules.audit.constants import ActionType, EventName
from app.modules.destinations.constants import SheetStatus
from app.modules.destinations.exceptions import NoSheetLink
from app.modules.destinations.models import SheetLink
from app.modules.destinations.selectors import locked_link_for, picker_cache_key
from app.modules.destinations.services.queue import queue_revoke
from app.modules.destinations.services.record import record_action


def disconnect_sheet(db: Session, *, user: User) -> SheetLink:
    """Stop delivering at once, and give the permission back straight after.

    The revocation is a worker's, queued on commit; until it succeeds the
    fingerprint stays, and the daily check pays what is owed. The file stays
    in the owner's Drive.
    """
    link = locked_link_for(db, owner=user)
    if link is None or link.status == SheetStatus.DISCONNECTED:
        raise NoSheetLink
    now = utcnow()
    previous = {"status": link.status, "spreadsheet_id": link.spreadsheet_id}
    link.status = SheetStatus.DISCONNECTED
    link.next_attempt_at = None
    db.flush()
    record_action(
        db,
        user=user,
        link=link,
        action=ActionType.SHEET_DISCONNECT,
        event=EventName.SHEET_DISCONNECTED,
        previous=previous,
        now=now,
    )
    on_commit(db, partial(queue_revoke, link_id=str(link.id)))
    # A picker token waiting for a file is part of the permission handed back.
    cache.delete(picker_cache_key(owner_id=user.id))
    db.commit()
    return link


__all__ = ["disconnect_sheet"]
