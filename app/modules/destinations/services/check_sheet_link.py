"""The daily look at a link that no lead came to test."""

from googlekit import GoogleError, SheetsClient
from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.modules.destinations.constants import BrokenReason, SheetMode, SheetStatus
from app.modules.destinations.models import SheetLink
from app.modules.destinations.selectors import checkable_links, form_sheets_for
from app.modules.destinations.services.access import open_sheets
from app.modules.destinations.services.sheet_state import (
    activate,
    mark_broken,
    mark_checked,
    settle,
)


def check_sheet_link(db: Session, *, link_id: str) -> str:
    """Is the permission still there, and is the file out of the bin?

    A file restored from the bin puts its link back to work by itself. With
    a file per form, one in the bin stops the link and all out starts it.
    ``moved`` when the owner pressed something while Google was answering.
    """
    found = checkable_links(db, link_id=link_id)
    if not found:
        return "gone"
    link = found[0]
    now = utcnow()
    try:
        with open_sheets(link=link) as client:
            trashed = _in_the_bin(db, link=link, client=client)
    except GoogleError as exc:
        return settle(db, link=link, error=exc, now=now)
    mark_checked(db, link=link, now=now)
    if trashed and link.status == SheetStatus.ACTIVE:
        stopped = mark_broken(db, link=link, reason=BrokenReason.TRASHED, now=now)
        return "trashed" if stopped else "moved"
    if not trashed and link.status == SheetStatus.BROKEN:
        return "restored" if activate(db, link=link, now=now) else "moved"
    return "ok"


def _in_the_bin(db: Session, *, link: SheetLink, client: SheetsClient) -> bool:
    if link.mode != SheetMode.PER_FORM:
        return bool(client.is_trashed(file_id=link.spreadsheet_id))
    return any(
        client.is_trashed(file_id=sheet.spreadsheet_id)
        for sheet in form_sheets_for(db, link=link)
    )


__all__ = ["check_sheet_link"]
