"""A forgotten password, replaced through the bot.

**Who may ask.** Only a Telegram chat a signed-in cabinet linked earlier.
The bot issues the token to that chat and to nobody else, so the link proves
what the bot's other messages already rely on: this phone is this account's.
There is no email delivery, which is why this is the only way back in that
does not go through the office.

**What the token is worth.** One password change on one account, within a
quarter of an hour. It carries a fingerprint of the password it was issued
against, so every link still lying in the chat dies the moment one of them
is used - or the password moves some other way.
"""

import hashlib
import hmac
import logging
import secrets
import uuid

from sqlalchemy.orm import Session

from app.common import tokens
from app.common.cache import cache
from app.common.config import settings
from app.common.db import utcnow
from app.common.exceptions import InputRefused
from app.common.passwords import PasswordInvalid, make_password, validate_password
from app.modules.accounts.constants import (
    RESET_TOKEN_BYTES,
    RESET_TOKEN_KEY,
    RESET_TTL_SECONDS,
)
from app.modules.accounts.exceptions import ResetLinkInvalid
from app.modules.accounts.models import User
from app.modules.audit.constants import EventName
from app.modules.audit.services import emit

logger = logging.getLogger(__name__)


def issue_password_reset(*, owner: User) -> str:
    """A fresh one-time token for this account's new password."""
    token = secrets.token_urlsafe(RESET_TOKEN_BYTES)
    cache.set(
        RESET_TOKEN_KEY.format(token=token),
        {"owner": str(owner.id), "stamp": _stamp(owner)},
        RESET_TTL_SECONDS,
    )
    logger.info("password_reset_issued", extra={"owner": str(owner.id)})
    return token


def reset_target(db: Session, *, token: str) -> User:
    """The account a live token belongs to, without spending it.

    Read when the form is drawn, so somebody holding a dead link is told at
    once rather than after typing a password twice.
    """
    payload = cache.get(RESET_TOKEN_KEY.format(token=token)) if token else None
    if not isinstance(payload, dict):
        raise ResetLinkInvalid
    try:
        owner = db.get(User, uuid.UUID(str(payload.get("owner", ""))))
    except ValueError:
        owner = None
    if (
        owner is None
        or not owner.is_active
        or not hmac.compare_digest(str(payload.get("stamp", "")), _stamp(owner))
    ):
        raise ResetLinkInvalid
    return owner


def reset_password(db: Session, *, token: str, new_password: str) -> User:
    """Spend the token and replace the password; every other device signs out
    and the linked phone is told.

    The token is spent only once the new password passed the rules: a weak
    one is a typing problem, and the reader tries again on the same link.
    """
    owner = reset_target(db, token=token)
    try:
        validate_password(new_password, email=owner.email, full_name=owner.full_name)
    except PasswordInvalid as exc:
        raise InputRefused({"new_password": str(exc)}) from exc
    cache.delete(RESET_TOKEN_KEY.format(token=token))
    owner.password = make_password(new_password)
    emit(
        db,
        owner_id=owner.id,
        name=EventName.USER_PASSWORD_CHANGED,
        aggregate_type="user",
        aggregate_id=owner.id,
    )
    # Late: the notifications module reads accounts, not the other way round.
    from app.modules.notifications.services import queue_password_changed

    queue_password_changed(db, owner=owner)
    db.commit()
    tokens.revoke_all(subject=str(owner.id), now=utcnow())
    logger.info("password_reset_spent", extra={"owner": str(owner.id)})
    return owner


def _stamp(owner: User) -> str:
    """A fingerprint of the password column, never the column itself."""
    key = f"accounts.reset{settings.secret_key}".encode()
    return hmac.new(key, owner.password.encode(), hashlib.sha256).hexdigest()[:24]


__all__ = ["issue_password_reset", "reset_password", "reset_target"]
