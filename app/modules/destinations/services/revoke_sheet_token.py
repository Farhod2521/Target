"""Handing a disconnected link's permission back to Google."""

import logging
import uuid

from googlekit import GoogleError, Unavailable, revoke
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.crypto import decrypt
from app.common.db import utcnow
from app.modules.destinations.constants import REVOKE_ACTIONS, SheetStatus
from app.modules.destinations.models import SheetLink
from app.modules.destinations.services.record import close_actions, fail_actions
from app.modules.destinations.services.sheet_state import forget_token

logger = logging.getLogger(__name__)


def revoke_sheet_token(db: Session, *, link_id: str) -> str:
    """Revoke the permission, then forget the token. Owed by every disconnect.

    Only for a link still disconnected: one connected again holds a new
    permission. A temporary failure leaves the token for the daily check;
    any other forgets it anyway, and the audit row says which happened.
    """
    try:
        key = uuid.UUID(str(link_id))
    except ValueError:
        return "nothing"
    link = db.scalar(
        select(SheetLink).where(
            SheetLink.id == key,
            SheetLink.status == SheetStatus.DISCONNECTED,
            SheetLink.token_fingerprint != "",
        ),
        execution_options={"populate_existing": True},
    )
    if link is None:
        return "nothing"
    now = utcnow()
    try:
        revoke(token=decrypt(bytes(link.token_encrypted)))
    except Unavailable:
        return "later"
    except GoogleError as exc:
        logger.warning(
            "sheet token revoke refused: owner=%s error=%s",
            link.owner_id,
            type(exc).__name__,
        )
        fail_actions(db, link=link, actions=REVOKE_ACTIONS, error=exc, now=now)
        outcome = "refused"
    else:
        close_actions(db, link=link, actions=REVOKE_ACTIONS, now=now)
        outcome = "revoked"
    forget_token(db, link=link, now=now)
    return outcome


__all__ = ["revoke_sheet_token"]
