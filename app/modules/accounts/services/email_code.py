"""Confirming an email behind an emailed code.

Signing up does not wait for this: the account opens at once, and a signed-in
user who wants to confirm their address asks for a five-digit code and sends
it back within CODE_SECONDS. Only the code's HMAC is kept, in the cache.
"""

import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass
from typing import Final

from sqlalchemy.orm import Session

from app.common import throttle
from app.common.cache import cache
from app.common.config import settings
from app.common.db import utcnow
from app.common.mail import MailNotSent, send_mail
from app.modules.accounts.emails import email_code_mail
from app.modules.accounts.exceptions import (
    CodeExpired,
    CodeTriesSpent,
    CodeWrong,
    EmailAlreadyVerified,
    MailUnavailable,
    ResendTooSoon,
    TooManyCodes,
)
from app.modules.accounts.models import User
from app.modules.audit.constants import EventName
from app.modules.audit.services import emit

CODE_LENGTH: Final = 5
CODE_SECONDS: Final = 3 * 60
RESEND_SECONDS: Final = 60
MAX_TRIES: Final = 5
SENDS_PER_HOUR: Final = 5
KEY: Final = "email:code:{user_id}"
SENDS_BUCKET: Final = "email:code:sends"


@dataclass(frozen=True, slots=True)
class CodeSent:
    email: str
    expires_in: int
    resend_in: int


def _key(user: User) -> str:
    return KEY.format(user_id=user.id)


def _digest(email: str, code: str) -> str:
    return hmac.new(
        settings.secret_key.encode(), f"{email}:{code}".encode(), hashlib.sha256
    ).hexdigest()


def _new_code() -> str:
    return f"{secrets.randbelow(10**CODE_LENGTH):0{CODE_LENGTH}d}"


def send_email_code(*, user: User) -> CodeSent:
    """Mail a fresh code to the user's address, at most once a minute."""
    if user.email_verified_at is not None:
        raise EmailAlreadyVerified
    now = time.time()
    held = cache.get(_key(user))
    if isinstance(held, dict):
        waited = now - held.get("sent_at", 0)
        if waited < RESEND_SECONDS:
            raise ResendTooSoon(seconds=int(RESEND_SECONDS - waited) + 1)
    if not throttle.hit(
        bucket=SENDS_BUCKET, key=str(user.id), limit=SENDS_PER_HOUR, window_seconds=3600
    ):
        raise TooManyCodes
    code = _new_code()
    try:
        send_mail(
            email_code_mail(
                to=user.email,
                name=user.full_name,
                code=code,
                minutes=CODE_SECONDS // 60,
                language=user.language,
            )
        )
    except MailNotSent as exc:
        raise MailUnavailable from exc
    cache.set(
        _key(user),
        {
            "code": _digest(user.email, code),
            "tries": 0,
            "sent_at": now,
            "expires_at": now + CODE_SECONDS,
        },
        timeout=CODE_SECONDS,
    )
    return CodeSent(email=user.email, expires_in=CODE_SECONDS, resend_in=RESEND_SECONDS)


def confirm_email(db: Session, *, user: User, code: str) -> User:
    """The right code in time marks the address confirmed."""
    if user.email_verified_at is not None:
        raise EmailAlreadyVerified
    held = cache.get(_key(user))
    if not isinstance(held, dict) or time.time() > held.get("expires_at", 0):
        raise CodeExpired
    if held.get("tries", 0) >= MAX_TRIES:
        raise CodeTriesSpent
    if not hmac.compare_digest(held["code"], _digest(user.email, code.strip())):
        held["tries"] = held.get("tries", 0) + 1
        cache.set(_key(user), held, timeout=CODE_SECONDS)
        left = MAX_TRIES - held["tries"]
        if left <= 0:
            raise CodeTriesSpent
        raise CodeWrong(left=left)
    cache.delete(_key(user))
    user.email_verified_at = utcnow()
    emit(
        db,
        owner_id=user.id,
        name=EventName.USER_EMAIL_VERIFIED,
        aggregate_type="user",
        aggregate_id=user.id,
        payload={"email": user.email},
    )
    db.commit()
    return user
