"""Another way of writing for a working link, without going back to Google."""

from datetime import timedelta
from functools import partial

from sqlalchemy.orm import Session

from app.common.db import on_commit, utcnow
from app.modules.accounts.models import User
from app.modules.audit.constants import ActionType, EventName
from app.modules.billing.selectors import has_live_subscription
from app.modules.destinations.constants import (
    PREPARE_GRACE_SECONDS,
    SheetMode,
    SheetStatus,
)
from app.modules.destinations.exceptions import (
    SheetModeLocked,
    SheetModeUnchanged,
    SheetSubscriptionRequired,
)
from app.modules.destinations.models import SheetLink
from app.modules.destinations.selectors import locked_link_for
from app.modules.destinations.services.choice import SheetChoice, check_choice
from app.modules.destinations.services.link_choice import apply_choice, snapshot
from app.modules.destinations.services.queue import queue_prepare
from app.modules.destinations.services.record import record_action


def change_sheet_mode(db: Session, *, user: User, choice: SheetChoice) -> SheetLink:
    """Point a working link at one file or a file per form, and order it.

    The permission the link holds makes either; a file of the owner's own
    needs the picker's token from Google's screen, so it is refused here.
    Recorded as a connection, which is what it is.
    """
    if not has_live_subscription(db, owner=user):
        raise SheetSubscriptionRequired
    link = locked_link_for(db, owner=user)
    if link is None or link.status != SheetStatus.ACTIVE:
        raise SheetModeLocked
    if choice.mode == SheetMode.OWN_FILE:
        raise SheetModeLocked
    choice = check_choice(db, user=user, choice=choice)
    if choice.mode == link.mode:
        raise SheetModeUnchanged
    now = utcnow()
    previous = snapshot(link)
    apply_choice(db, link=link, choice=choice, created=False, now=now)
    link.status = SheetStatus.PREPARING
    link.caught_up_at = None
    link.last_error_code = ""
    link.next_attempt_at = now + timedelta(seconds=PREPARE_GRACE_SECONDS)
    db.flush()
    record_action(
        db,
        user=user,
        link=link,
        action=ActionType.SHEET_CONNECT,
        event=EventName.SHEET_CONNECTED,
        previous=previous,
        now=now,
    )
    on_commit(db, partial(queue_prepare, link_id=str(link.id)))
    db.commit()
    return link


__all__ = ["change_sheet_mode"]
