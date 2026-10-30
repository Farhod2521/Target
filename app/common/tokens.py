from datetime import datetime, timedelta
from typing import Any

import jwt

from app.common.cache import cache
from app.common.config import settings

ALGORITHM = "HS256"
ACCESS_MINUTES = 60
REFRESH_DAYS = 30
REVOKED_KEY = "tokens:revoked_before:{subject}"


def issue(*, subject: str, kind: str, now: datetime) -> str:
    life = (
        timedelta(minutes=ACCESS_MINUTES)
        if kind == "access"
        else timedelta(days=REFRESH_DAYS)
    )
    payload: dict[str, Any] = {
        "sub": subject,
        "typ": kind,
        "iat": now,
        # ``iat`` is whole seconds; a pair issued right after a password change
        # would otherwise share the second its revocation was stamped with.
        "t": now.timestamp(),
        "exp": now + life,
    }
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def read(token: str, *, kind: str) -> str | None:
    try:
        payload = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
    except jwt.PyJWTError:
        return None
    if payload.get("typ") != kind:
        return None
    subject = str(payload.get("sub") or "")
    if not subject:
        return None
    revoked = cache.get(REVOKED_KEY.format(subject=subject))
    issued = float(payload.get("t") or payload.get("iat") or 0)
    if revoked is not None and issued < float(revoked):
        return None
    return subject


def revoke_all(*, subject: str, now: datetime) -> None:
    """Every token issued to ``subject`` up to ``now`` stops working - the
    signing out everywhere a changed password owes, as Django's session hash
    gave it. A token issued at ``now`` itself survives: it is the fresh pair
    handed to the device that made the change. Kept as long as the longest
    token lives."""
    cache.set(
        REVOKED_KEY.format(subject=subject),
        now.timestamp(),
        timeout=int(timedelta(days=REFRESH_DAYS).total_seconds()),
    )
