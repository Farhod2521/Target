"""The owner's pick in Google's file picker: which of their files to write into."""

import re
from datetime import timedelta
from functools import partial

from sqlalchemy.orm import Session

from app.common.db import on_commit, utcnow
from app.modules.accounts.models import User
from app.modules.audit.constants import ActionType, EventName
from app.modules.destinations.constants import (
    FILE_ID_PATTERN,
    PREPARE_GRACE_SECONDS,
    SheetMode,
    SheetStatus,
)
from app.modules.destinations.exceptions import BadFileChoice, NotChoosingFile
from app.modules.destinations.models import SheetLink
from app.modules.destinations.selectors import locked_link_for
from app.modules.destinations.services.queue import queue_prepare
from app.modules.destinations.services.record import close_actions, record_action


def choose_own_file(db: Session, *, user: User, file_id: str) -> SheetLink:
    """Point the link at the picked file and have a worker open it.

    The id is only stored here; whether it is a writable spreadsheet is the
    worker's to ask. The same file again keeps the tab of ours in it. The
    connection's own press closes here: its permission is held.
    """
    if not re.fullmatch(FILE_ID_PATTERN, file_id):
        raise BadFileChoice
    link = locked_link_for(db, owner=user)
    if link is None or link.status != SheetStatus.CHOOSING:
        raise NotChoosingFile
    if link.mode != SheetMode.OWN_FILE:
        raise NotChoosingFile
    now = utcnow()
    previous = {"status": link.status, "spreadsheet_id": link.spreadsheet_id}
    if file_id != link.spreadsheet_id:
        link.spreadsheet_id = file_id
        link.sheet_id = ""
        link.spreadsheet_url = ""
        link.columns = []
    link.status = SheetStatus.PREPARING
    link.last_error_code = ""
    link.next_attempt_at = now + timedelta(seconds=PREPARE_GRACE_SECONDS)
    db.flush()
    close_actions(db, link=link, actions=(ActionType.SHEET_CONNECT,), now=now)
    record_action(
        db,
        user=user,
        link=link,
        action=ActionType.SHEET_PICK,
        event=EventName.SHEET_PICKED,
        previous=previous,
        now=now,
    )
    on_commit(db, partial(queue_prepare, link_id=str(link.id)))
    db.commit()
    return link


__all__ = ["choose_own_file"]
