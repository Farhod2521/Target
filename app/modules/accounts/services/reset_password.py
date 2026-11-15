"""A forgotten password, replaced through the bot or the account's email.

**Who may ask.** A Telegram chat a signed-in cabinet linked earlier, or
whoever reads the account's mailbox. The token goes only to one of those two
places, so the link proves the reader holds this phone or this address.
The sign-in page that asks by email is answered the same whether the
address is signed up or not, and the letter leaves from the worker, so
neither the words nor the time taken tell which emails have accounts.

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
from app.common.mail import MailNotSent, send_mail
from app.common.passwords import PasswordInvalid, make_password, validate_password
from app.common.routes import reverse
from app.modules.accounts.constants import (
    RESET_TOKEN_BYTES,
    RESET_TOKEN_KEY,
    RESET_TTL_SECONDS,
)
from app.modules.accounts.emails import password_reset_mail
from app.modules.accounts.exceptions import ResetLinkInvalid
from app.modules.accounts.models import User
from app.modules.accounts.selectors.user_by_email import user_by_email
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


def mail_password_reset(db: Session, *, email: str) -> bool:
    """The new-password link to this address, when it opens an account.

    Silent about an unknown or closed account: the page that asked has
    already said "if the address is ours, a letter is on its way".
    """
    owner = user_by_email(db, email=email)
    if owner is None or not owner.is_active:
        return False
    path = reverse("accounts:password_reset", [issue_password_reset(owner=owner)])
    try:
        send_mail(
            password_reset_mail(
                to=owner.email,
                name=owner.full_name,
                url=f"{settings.site_url}{path}",
                minutes=RESET_TTL_SECONDS // 60,
                language=owner.language,
            )
        )
    except MailNotSent:
        logger.warning("password_reset_mail_failed", extra={"owner": str(owner.id)})
        return False
    logger.info("password_reset_mailed", extra={"owner": str(owner.id)})
    return True


def _stamp(owner: User) -> str:
    """A fingerprint of the password column, never the column itself."""
    key = f"accounts.reset{settings.secret_key}".encode()
    return hmac.new(key, owner.password.encode(), hashlib.sha256).hexdigest()[:24]


__all__ = [
    "issue_password_reset",
    "mail_password_reset",
    "reset_password",
    "reset_target",
]
