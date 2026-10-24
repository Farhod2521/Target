"""The free allowance, and where it is counted; and who a visitor's call is billed to."""

import secrets
from dataclasses import dataclass
from typing import Final

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.cache import cache
from app.modules.accounts.models import User
from app.modules.chat.constants import FREE_QUESTIONS, FREE_WINDOW_HOURS

KEY: Final = "chat:free:{scope}"
WINDOW_SECONDS: Final = FREE_WINDOW_HOURS * 3600
PUBLIC_CHAT_EMAIL: Final = "public-chat@targetolog.invalid"


@dataclass(frozen=True, slots=True)
class Allowance:
    """What is left, for the line under the chat box."""

    used: int
    limit: int

    @property
    def remaining(self) -> int:
        return max(0, self.limit - self.used)

    @property
    def is_spent(self) -> bool:
        return self.used >= self.limit


def scope_for(*, user_id: str, ip: str, session_key: str) -> str:
    """Who the allowance belongs to."""
    if user_id:
        return f"u:{user_id}"
    return f"g:{ip}:{session_key}"


def allowance(*, scope: str) -> Allowance:
    return Allowance(
        used=int(cache.get(KEY.format(scope=scope), 0) or 0), limit=FREE_QUESTIONS
    )


def consume(*, scope: str) -> Allowance:
    """Count one question. The window starts at the first one."""
    key = KEY.format(scope=scope)
    cache.add(key, 0, timeout=WINDOW_SECONDS)
    try:
        used = int(cache.incr(key))
    except ValueError:
        cache.set(key, 1, timeout=WINDOW_SECONDS)
        used = 1
    return Allowance(used=used, limit=FREE_QUESTIONS)


def public_chat_owner(db: Session) -> User:
    """The account visitors' questions are charged to. Created on first use."""
    owner = db.scalar(select(User).where(User.email == PUBLIC_CHAT_EMAIL))
    if owner is None:
        owner = User(
            email=PUBLIC_CHAT_EMAIL,
            full_name="Public chat",
            is_active=False,
            password="!" + secrets.token_urlsafe(30),
        )
        db.add(owner)
        db.flush()
    return owner


__all__ = [
    "PUBLIC_CHAT_EMAIL",
    "Allowance",
    "allowance",
    "consume",
    "public_chat_owner",
    "scope_for",
]
