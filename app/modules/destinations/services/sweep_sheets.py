"""What the minute, and the day, have for the worker."""

from datetime import datetime

from sqlalchemy.orm import Session

from app.modules.destinations.constants import SheetStatus
from app.modules.destinations.selectors import (
    checkable_links,
    due_links,
    has_work,
    links_owing_revocation,
    sheets_enabled,
)
from app.modules.destinations.services.queue import (
    queue_check,
    queue_delivery,
    queue_prepare,
    queue_revoke,
)


def sweep_sheets(db: Session, *, now: datetime) -> int:
    """Queue a run for every link with something to do. Returns how many.

    Files to make first - a person is watching the screen for those - then
    leads to send. The next tick is every retry there is.
    """
    if not sheets_enabled():
        return 0
    queued = 0
    for link in due_links(db, status=SheetStatus.PREPARING, now=now):
        queue_prepare(link_id=str(link.id))
        queued += 1
    for link in due_links(db, status=SheetStatus.ACTIVE, now=now):
        if has_work(db, link=link, now=now):
            queue_delivery(link_id=str(link.id))
            queued += 1
    return queued


def sweep_sheet_checks(db: Session) -> int:
    """Queue the daily check for each link, and each revocation still owed."""
    if not sheets_enabled():
        return 0
    checks = [str(link.id) for link in checkable_links(db)]
    owed = [str(pk) for pk in links_owing_revocation(db)]
    for link_id in checks:
        queue_check(link_id=link_id)
    for link_id in owed:
        queue_revoke(link_id=link_id)
    return len(checks) + len(owed)


__all__ = ["sweep_sheet_checks", "sweep_sheets"]
