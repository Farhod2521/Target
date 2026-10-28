"""The second half of connecting: Google's answer stored, and the file ordered."""

import logging
from datetime import datetime, timedelta
from functools import partial

from googlekit import SCOPE_DRIVE_FILE, AccessRevoked, GoogleError, Grant, exchange_code
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.common.cache import cache
from app.common.config import settings
from app.common.crypto import encrypt, fingerprint
from app.common.db import on_commit, utcnow
from app.modules.accounts.models import User
from app.modules.audit.constants import ActionType, EventName
from app.modules.billing.selectors import has_live_subscription
from app.modules.destinations.constants import (
    PICKER_TOKEN_MARGIN_SECONDS,
    PREPARE_GRACE_SECONDS,
    SheetStatus,
)
from app.modules.destinations.exceptions import (
    DrivePermissionMissing,
    GoogleStateMismatch,
    GoogleUnreachable,
    SheetSubscriptionRequired,
)
from app.modules.destinations.models import SheetLink
from app.modules.destinations.selectors import locked_link_for, picker_cache_key
from app.modules.destinations.services.choice import SheetChoice, check_choice
from app.modules.destinations.services.link_choice import (
    apply_choice,
    needs_pick,
    snapshot,
)
from app.modules.destinations.services.queue import queue_prepare
from app.modules.destinations.services.record import record_action

logger = logging.getLogger(__name__)


def connect_sheet(
    db: Session,
    *,
    user: User,
    code: str,
    redirect_uri: str,
    choice: SheetChoice | None,
) -> SheetLink:
    """Trade the callback's code for a permission, store it, and order the file.

    The code is traded here, inside the request: it is single-use and lives
    minutes. The subscription and the choice are checked a second time - a
    minute on Google's screens is a minute either can lapse in. An owner who
    chose a file of their own is left choosing it, the access token kept for
    the picker.
    """
    if not has_live_subscription(db, owner=user):
        raise SheetSubscriptionRequired
    if choice is not None:
        choice = check_choice(db, user=user, choice=choice)
    grant = _exchange(code=code, redirect_uri=redirect_uri)
    if not grant.holds(SCOPE_DRIVE_FILE):
        raise DrivePermissionMissing
    if not grant.refresh_token:
        # ``prompt=consent`` makes Google send one every time, so this is a
        # change on Google's side rather than anything the person did.
        logger.error("google grant arrived without a refresh token: owner=%s", user.id)
        raise GoogleUnreachable
    link = _store(db, user=user, grant=grant, choice=choice)
    if link.status == SheetStatus.CHOOSING:
        _keep_for_picker(user=user, grant=grant)
    return link


def _exchange(*, code: str, redirect_uri: str) -> Grant:
    """The code as a grant, or the sentence that explains why not."""
    try:
        return exchange_code(
            client_id=settings.google_oauth_client_id,
            client_secret=settings.google_oauth_client_secret,
            redirect_uri=redirect_uri,
            code=code,
        )
    except AccessRevoked as exc:
        # A code already used or expired: to the person, an old handshake.
        raise GoogleStateMismatch from exc
    except GoogleError as exc:
        logger.warning("google code exchange failed: %s", type(exc).__name__)
        raise GoogleUnreachable from exc


def _store(
    db: Session, *, user: User, grant: Grant, choice: SheetChoice | None
) -> SheetLink:
    """The permission on the owner's one link row, and a worker told to make the file.

    The same row whether this is the first connection or the fifth; made
    under the one-per-owner rule rather than read and then inserted, so two
    first connections at once update one row.
    """
    now = utcnow()
    link, created = _get_or_create(db, user=user, now=now)
    previous = {} if created else snapshot(link)
    apply_choice(db, link=link, choice=choice, created=created, now=now)
    _hold(link=link, grant=grant, now=now)
    if needs_pick(link=link, choice=choice):
        link.status = SheetStatus.CHOOSING
        link.next_attempt_at = None
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
    if link.status == SheetStatus.PREPARING:
        on_commit(db, partial(queue_prepare, link_id=str(link.id)))
    db.commit()
    return link


def _get_or_create(db: Session, *, user: User, now: datetime) -> tuple[SheetLink, bool]:
    link = locked_link_for(db, owner=user)
    if link is not None:
        return link, False
    made = db.execute(
        insert(SheetLink)
        .values(owner_id=user.id, token_encrypted=b"", created_at=now, updated_at=now)
        .on_conflict_do_nothing(index_elements=["owner_id"])
        .returning(SheetLink.id)
    ).scalar()
    link = locked_link_for(db, owner=user)
    if link is None:
        raise RuntimeError("sheet link vanished between insert and lock")
    return link, made is not None


def _keep_for_picker(*, user: User, grant: Grant) -> None:
    """Hold the access token for the picker, encrypted, until just before it dies."""
    seconds = grant.expires_in - PICKER_TOKEN_MARGIN_SECONDS
    if seconds <= 0 or not grant.access_token:
        return
    cache.set(
        picker_cache_key(owner_id=user.id),
        encrypt(grant.access_token).decode(),
        seconds,
    )


def _hold(*, link: SheetLink, grant: Grant, now: datetime) -> None:
    """The new permission on the row, and the row back to being prepared."""
    link.token_encrypted = encrypt(grant.refresh_token)
    link.token_fingerprint = fingerprint(grant.refresh_token)
    link.scopes = list(grant.scopes)
    link.google_email = grant.email
    link.status = SheetStatus.PREPARING
    link.broken_reason = ""
    link.broken_at = None
    link.caught_up_at = None
    link.last_error_code = ""
    link.connected_at = now
    # The task queued on commit makes the file; this keeps the sweep from
    # queueing a second one while the first is still at Google.
    link.next_attempt_at = now + timedelta(seconds=PREPARE_GRACE_SECONDS)


__all__ = ["connect_sheet"]
