"""``initData``: proving that a page opened inside Telegram is who it says."""

import hmac
import json
from hashlib import sha256
from typing import Any, Final
from urllib.parse import parse_qsl, quote

from pydantic import BaseModel, ConfigDict

from telegramkit.updates import Sender

SECRET_SALT: Final = b"WebAppData"

HASH_FIELD: Final = "hash"

DEFAULT_MAX_AGE_SECONDS: Final = 24 * 60 * 60


class InitDataError(Exception):
    """The payload cannot be trusted."""

    def __init__(self, reason: str, *, keys: tuple[str, ...] = ()) -> None:
        super().__init__(reason)
        self.reason = reason
        self.keys = keys


class InitDataExpired(InitDataError):
    """The signature is genuine and the payload is too old."""

    def __init__(
        self, reason: str, *, keys: tuple[str, ...] = (), age_seconds: int = 0
    ) -> None:
        super().__init__(reason, keys=keys)
        self.age_seconds = age_seconds


class VerifiedInitData(BaseModel):
    """A payload whose HMAC checked out.

    Only exists once the digest matched, so holding one is proof the blob
    came from Telegram signed with this bot's token.

    ``signed_keys`` is what the digest actually covered. Carried because
    the caller logs it, and it is field **names** rather than values - the
    line that names whatever Telegram adds next, before it turns into
    refusals nobody can explain.
    """

    model_config = ConfigDict(frozen=True)

    user: Sender
    signed_keys: tuple[str, ...]


def parse_init_data(
    raw: str,
    *,
    bot_token: str,
    now: int,
    max_age_seconds: int = DEFAULT_MAX_AGE_SECONDS,
) -> VerifiedInitData:
    """Verify one ``initData`` string and return whose it is."""
    if not bot_token:
        raise InitDataError("no-token")
    if not raw:
        raise InitDataError("empty")

    fields = _fields(raw)
    keys = tuple(sorted(fields))

    claimed = fields.get(HASH_FIELD, "")
    if not claimed:
        raise InitDataError("no-hash", keys=keys)

    if not hmac.compare_digest(claimed, _digest(fields=fields, bot_token=bot_token)):
        raise InitDataError("bad-signature", keys=keys)

    _check_age(fields=fields, keys=keys, now=now, max_age_seconds=max_age_seconds)
    return VerifiedInitData(
        user=_user(fields, keys=keys),
        signed_keys=tuple(key for key in keys if key != HASH_FIELD),
    )


def build_init_data(
    fields: dict[str, str], *, bot_token: str, hash_override: str = ""
) -> str:
    """Sign a payload the way Telegram does."""
    digest = hash_override or _digest(fields=fields, bot_token=bot_token)
    parts = [*fields.items(), (HASH_FIELD, digest)]
    return "&".join(
        f"{quote(key, safe='')}={quote(value, safe='')}" for key, value in parts
    )


def _fields(raw: str) -> dict[str, str]:
    """The query string as a mapping, decoded the way every client decodes it."""
    try:
        pairs = parse_qsl(raw, keep_blank_values=True, strict_parsing=True)
    except ValueError:
        raise InitDataError("malformed") from None

    fields: dict[str, str] = {}
    for key, value in pairs:
        if key in fields:
            raise InitDataError("repeated-field", keys=(*sorted(fields), key))
        fields[key] = value
    return fields


def _digest(*, fields: dict[str, str], bot_token: str) -> str:
    """The HMAC Telegram would have written over these fields."""
    checked = sorted((key, value) for key, value in fields.items() if key != HASH_FIELD)
    check_string = "\n".join(f"{key}={value}" for key, value in checked)

    secret = hmac.new(SECRET_SALT, bot_token.encode("utf-8"), sha256).digest()
    return hmac.new(secret, check_string.encode("utf-8"), sha256).hexdigest()


def _check_age(
    *, fields: dict[str, str], keys: tuple[str, ...], now: int, max_age_seconds: int
) -> None:
    """Refuse a genuine proof that has been lying around."""
    raw = fields.get("auth_date", "")
    try:
        issued_at = int(raw)
    except ValueError:
        raise InitDataError("no-auth-date", keys=keys) from None

    age = now - issued_at
    if age < 0:
        raise InitDataExpired("future-date", keys=keys, age_seconds=age)
    if age > max_age_seconds:
        raise InitDataExpired("expired", keys=keys, age_seconds=age)


def _user(fields: dict[str, str], *, keys: tuple[str, ...]) -> Sender:
    """The ``user`` field, which is JSON inside the query string."""
    raw = fields.get("user", "")
    if not raw:
        raise InitDataError("no-user", keys=keys)
    try:
        payload = json.loads(raw)
    except ValueError:
        raise InitDataError("user-not-json", keys=keys) from None
    if not isinstance(payload, dict):
        raise InitDataError("user-not-object", keys=keys)

    identifier = payload.get("id")
    if not isinstance(identifier, int) or isinstance(identifier, bool):
        raise InitDataError("user-has-no-id", keys=keys)

    return Sender(id=str(identifier), username=_text(payload.get("username")))


def _text(value: Any) -> str:
    return value if isinstance(value, str) else ""


__all__ = [
    "DEFAULT_MAX_AGE_SECONDS",
    "HASH_FIELD",
    "SECRET_SALT",
    "InitDataError",
    "InitDataExpired",
    "VerifiedInitData",
    "build_init_data",
    "parse_init_data",
]
