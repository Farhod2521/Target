"""What a connection does to a link's start and file, by what the owner chose.

What they choose starts from now; what happened to them loses nothing. A
first connection, one after "Uzish", another way of writing, another file
of their own each start the spreadsheet at that moment. A permission Google
took back or a file that went missing keep the start the link had.
"""

import uuid
from datetime import datetime

from sqlalchemy import delete
from sqlalchemy.orm import Session

from app.modules.destinations.constants import Channel, SheetMode, SheetStatus
from app.modules.destinations.models import LeadDelivery, SheetLink
from app.modules.destinations.services.choice import SheetChoice


def apply_choice(
    db: Session,
    *,
    link: SheetLink,
    choice: SheetChoice | None,
    created: bool,
    now: datetime,
) -> None:
    """Set the link's start, way of writing and file for this connection.

    On the unsaved row, before its status moves. ``choice`` is ``None`` for
    the press that mends a stopped link. Another way of writing forgets the
    file and every delivery to it.
    """
    changed = choice is not None and not created and _differs(link, choice)
    if _starts_again(link=link, choice=choice, created=created, changed=changed):
        link.deliver_from = now
    if choice is None:
        return
    if changed:
        _forget_file(db, link)
    link.mode = choice.mode
    link.only_form_id = uuid.UUID(choice.only_form_id) if choice.only_form_id else None


def needs_pick(*, link: SheetLink, choice: SheetChoice | None) -> bool:
    """Whether the owner still has a file of their own to pick."""
    if link.mode != SheetMode.OWN_FILE:
        return False
    return choice is not None or not link.spreadsheet_id


def snapshot(link: SheetLink) -> dict[str, str]:
    """What undoing a choice by hand needs back: state, file, choice, start."""
    since = link.deliver_from.isoformat() if link.deliver_from else ""
    return {
        "status": link.status,
        "spreadsheet_id": link.spreadsheet_id,
        "mode": link.mode,
        "only_form_id": str(link.only_form_id or ""),
        "deliver_from": since,
    }


def _starts_again(
    *, link: SheetLink, choice: SheetChoice | None, created: bool, changed: bool
) -> bool:
    if created or link.status == SheetStatus.DISCONNECTED:
        return True
    if choice is None:
        return False
    # Picking a file of their own again is a new choice - except as the fix
    # for a stopped link, and as a second sign-in while a pick still waits.
    waiting = link.status in {SheetStatus.BROKEN, SheetStatus.CHOOSING}
    repick = choice.mode == SheetMode.OWN_FILE and not waiting
    return changed or repick


def _differs(link: SheetLink, choice: SheetChoice) -> bool:
    return link.mode != choice.mode or str(link.only_form_id or "") != (
        choice.only_form_id
    )


def _forget_file(db: Session, link: SheetLink) -> None:
    link.spreadsheet_id = ""
    link.sheet_id = ""
    link.spreadsheet_url = ""
    link.columns = []
    db.execute(
        delete(LeadDelivery)
        .where(
            LeadDelivery.owner_id == link.owner_id,
            LeadDelivery.channel == Channel.SHEETS,
        )
        .execution_options(synchronize_session=False)
    )


__all__ = ["apply_choice", "needs_pick", "snapshot"]
