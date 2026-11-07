"""The Login Widget: proving that a browser came back from Telegram's own
sign-in page as the Telegram account it names.

The widget sends the browser to our address with the account's fields and
a ``hash`` in the query string. Unlike a Mini App's ``initData``, the key is
SHA-256 of the bot token itself (Telegram's "Checking authorization").
Only Telegram's fields are signed; anything else in the query is ours.
"""

import hmac
from hashlib import sha256
from typing import Final

from pydantic import BaseModel, ConfigDict, Field

# What Telegram puts in the redirect; the digest covers whichever of these came.
LOGIN_FIELDS: Final = frozenset(
    {"id", "first_name", "last_name", "username", "photo_url", "auth_date"}
)
HASH_FIELD: Final = "hash"


class LoginWidgetError(Exception):
    """The redirect cannot be trusted: no hash, a wrong one, or too old."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class TelegramLogin(BaseModel):
    """A Telegram account whose redirect checked out. ``id`` is the user's
    id, which is also their private chat with the bot."""

    model_config = ConfigDict(frozen=True)

    id: int
    first_name: str = Field(default="", repr=False)
    last_name: str = Field(default="", repr=False)
    username: str = ""

    @property
    def name(self) -> str:
        return " ".join(p for p in (self.first_name, self.last_name) if p).strip()


def verify_login(
    query: dict[str, str], *, bot_token: str, now: int, max_age_seconds: int
) -> TelegramLogin:
    """Check one redirect's query (extra keys of ours are left out of the digest)."""
    if not bot_token:
        raise LoginWidgetError("no-token")
    claimed = query.get(HASH_FIELD, "")
    if not claimed:
        raise LoginWidgetError("no-hash")
    fields = {k: v for k, v in query.items() if k in LOGIN_FIELDS}
    if not hmac.compare_digest(claimed, login_digest(fields, bot_token=bot_token)):
        raise LoginWidgetError("bad-signature")
    try:
        issued_at = int(fields.get("auth_date", ""))
        user_id = int(fields.get("id", ""))
    except ValueError:
        raise LoginWidgetError("malformed") from None
    age = now - issued_at
    if age < -60 or age > max_age_seconds:
        raise LoginWidgetError("expired")
    return TelegramLogin(
        id=user_id,
        first_name=fields.get("first_name", ""),
        last_name=fields.get("last_name", ""),
        username=fields.get("username", ""),
    )


def login_digest(fields: dict[str, str], *, bot_token: str) -> str:
    """The hash Telegram writes over these fields; tests sign with it too."""
    check_string = "\n".join(f"{k}={v}" for k, v in sorted(fields.items()))
    secret = sha256(bot_token.encode("utf-8")).digest()
    return hmac.new(secret, check_string.encode("utf-8"), sha256).hexdigest()


__all__ = ["LoginWidgetError", "TelegramLogin", "login_digest", "verify_login"]
