from datetime import datetime, timedelta
from typing import Any

import jwt

from app.common.config import settings

ALGORITHM = "HS256"
ACCESS_MINUTES = 60
REFRESH_DAYS = 30


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
    return str(payload.get("sub") or "") or None
