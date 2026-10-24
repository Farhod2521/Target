"""Signing up behind an emailed code.

The account is not made until the code comes back: the form is kept in the
cache with the password already hashed, a five-digit code goes to the address,
and the right code within CODE_SECONDS creates the user. Nothing is written to
the database for an address nobody confirms.
"""

import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass
from typing import Any, Final

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common import throttle
from app.common.cache import cache
from app.common.config import settings
from app.common.mail import MailNotSent, send_mail
from app.common.passwords import PasswordInvalid, make_password, validate_password
from app.modules.accounts.emails import signup_code_mail
from app.modules.accounts.exceptions import (
    CodeExpired,
    CodeTriesSpent,
    CodeWrong,
    EmailTaken,
    MailUnavailable,
    ResendTooSoon,
    TooManyCodes,
)
from app.modules.accounts.models import User
from app.modules.accounts.phone import normalize_email

CODE_LENGTH: Final = 5
CODE_SECONDS: Final = 3 * 60
RESEND_SECONDS: Final = 60
MAX_TRIES: Final = 5
KEEP_SECONDS: Final = 30 * 60
SENDS_PER_HOUR: Final = 5
KEY: Final = "signup:pending:{email}"
SENDS_BUCKET: Final = "signup:sends"


@dataclass(frozen=True, slots=True)
class CodeSent:
    email: str
    expires_in: int
    resend_in: int


def _key(email: str) -> str:
    return KEY.format(email=email)


def _digest(email: str, code: str) -> str:
    return hmac.new(
        settings.secret_key.encode(), f"{email}:{code}".encode(), hashlib.sha256
    ).hexdigest()


def _new_code() -> str:
    return f"{secrets.randbelow(10**CODE_LENGTH):0{CODE_LENGTH}d}"


def _send(email: str, pending: dict[str, Any], *, now: float) -> CodeSent:
    if not throttle.hit(
        bucket=SENDS_BUCKET, key=email, limit=SENDS_PER_HOUR, window_seconds=3600
    ):
        raise TooManyCodes
    code = _new_code()
    pending |= {
        "code": _digest(email, code),
        "tries": 0,
        "sent_at": now,
        "expires_at": now + CODE_SECONDS,
    }
    try:
        send_mail(
            signup_code_mail(
                to=email,
                name=pending["full_name"],
                code=code,
                minutes=CODE_SECONDS // 60,
                language=pending["language"],
            )
        )
    except MailNotSent as exc:
        raise MailUnavailable from exc
    cache.set(_key(email), pending, timeout=KEEP_SECONDS)
    return CodeSent(email=email, expires_in=CODE_SECONDS, resend_in=RESEND_SECONDS)


def _taken(db: Session, email: str) -> bool:
    return db.scalar(select(User.id).where(User.email == email)) is not None


def start_signup(
    db: Session,
    *,
    email: str,
    full_name: str,
    password: str,
    phone: str,
    language: str,
    referral_code: str = "",
) -> CodeSent:
    """Check the form, keep it, and mail the code. No account yet."""
    email = normalize_email(email)
    if _taken(db, email):
        raise EmailTaken
    try:
        validate_password(password, email=email, full_name=full_name)
    except PasswordInvalid as exc:
        from app.common.exceptions import DomainError

        raise DomainError(str(exc)) from exc
    now = time.time()
    held = cache.get(_key(email))
    if isinstance(held, dict) and now - held.get("sent_at", 0) < RESEND_SECONDS:
        raise ResendTooSoon(seconds=int(RESEND_SECONDS - (now - held["sent_at"])) + 1)
    pending = {
        "full_name": full_name.strip(),
        "password_hash": make_password(password),
        "phone": phone,
        "language": str(language),
        "referral_code": referral_code,
    }
    return _send(email, pending, now=now)


def resend_code(*, email: str) -> CodeSent:
    email = normalize_email(email)
    held = cache.get(_key(email))
    if not isinstance(held, dict):
        raise CodeExpired
    now = time.time()
    waited = now - held.get("sent_at", 0)
    if waited < RESEND_SECONDS:
        raise ResendTooSoon(seconds=int(RESEND_SECONDS - waited) + 1)
    return _send(email, held, now=now)


def confirm_signup(db: Session, *, email: str, code: str) -> User:
    """The right code in time makes the account; it is then signed in."""
    from app.modules.accounts.services.register_user import register_user

    email = normalize_email(email)
    held = cache.get(_key(email))
    if not isinstance(held, dict) or time.time() > held.get("expires_at", 0):
        raise CodeExpired
    if held.get("tries", 0) >= MAX_TRIES:
        raise CodeTriesSpent
    if not hmac.compare_digest(held["code"], _digest(email, code.strip())):
        held["tries"] = held.get("tries", 0) + 1
        cache.set(_key(email), held, timeout=KEEP_SECONDS)
        left = MAX_TRIES - held["tries"]
        if left <= 0:
            raise CodeTriesSpent
        raise CodeWrong(left=left)
    cache.delete(_key(email))
    if _taken(db, email):
        raise EmailTaken
    return register_user(
        db,
        email=email,
        full_name=held["full_name"],
        password_hash=held["password_hash"],
        phone=held["phone"],
        language=held["language"],
        referral_code=held["referral_code"],
    )
