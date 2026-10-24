"""``initData``: proving that a page opened inside Telegram is who it says.

A Mini App is an ordinary web page in a WebView, so the server sees an
ordinary request. What makes it trustworthy is a blob Telegram hands the
page in JavaScript - a query string of fields with an HMAC over them,
signed with a key derived from the bot token. Anybody holding the token
can check it; nobody without the token can forge it.

Pure functions, no Django, no clock. This is the security boundary of a
public endpoint, so it has to be testable without a database, a request
object or a settings module - the token and the current time both arrive
as arguments. ``metaads.signed_request`` is the same file for Meta's
deletion callback, and this one follows it deliberately.

**The format is copied from a working implementation, not inferred.**
Two details are settled that way rather than by reading the documentation
- see :data:`HASH_FIELD` and :func:`_fields`. Where the prose is
ambiguous, the tie-breaker is what libraries that receive real payloads
every day actually do.

**Failures carry a machine-readable reason.** Not shown to anybody: the
caller turns every one of them into the same sentence, because telling a
forger which check failed tells them how far they got. The reason exists
so a log line can say what a person on a phone must not be told.
"""

import hmac
import json
from hashlib import sha256
from typing import Any, Final
from urllib.parse import parse_qsl, quote

from pydantic import BaseModel, ConfigDict

from telegramkit.updates import Sender

# What Telegram derives the signing key from. The bot token is the message
# and this constant is the key - not the other way round, which is the
# mistake that produces a digest that never matches and a bug nobody can
# see by reading it.
SECRET_SALT: Final = b"WebAppData"

# The field that carries the digest, and the only field left out of it.
#
# **The only one, including ``signature``.** Telegram's Ed25519 value is
# inside the check string like everything else: the documentation's
# "except hash and signature" belongs to the Ed25519 procedure, which is a
# different check string with a ``bot_id`` prefix, while the HMAC section
# says "all received fields". A real payload verifies with ``signature``
# inside the digest; excluding it refuses every payload a modern client
# sends, while still passing a test whose helper excludes it too.
HASH_FIELD: Final = "hash"

# How long a proof is worth trusting. Telegram's own guidance, and the
# ceiling rather than the value: the caller passes what it wants.
DEFAULT_MAX_AGE_SECONDS: Final = 24 * 60 * 60


class InitDataError(Exception):
    """The payload cannot be trusted.

    ``reason`` is a stable slug for a log line and ``keys`` names the
    fields that arrived - never their values, which carry a person's name
    and Telegram id. Neither is meant for a reader: the caller answers
    every one of these with one sentence, because a caller that could
    tell them apart could tell a forger which half of their guess was
    right.
    """

    def __init__(self, reason: str, *, keys: tuple[str, ...] = ()) -> None:
        super().__init__(reason)
        self.reason = reason
        self.keys = keys


class InitDataExpired(InitDataError):
    """The signature is genuine and the payload is too old.

    Separate from its parent on purpose, and safely: this is only reached
    once the HMAC has checked out, so whoever sees it already holds
    something Telegram signed. It is also the one failure with an action
    behind it - open the app again from the bot - which is a sentence
    worth having.

    ``age_seconds`` is how far past the limit it was. A handful of
    seconds is a clock that drifted; a day is a page left open.
    """

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
    """Verify one ``initData`` string and return whose it is.

    The account is the same :class:`~telegramkit.updates.Sender` a button
    press carries, because it is the same account: an id to decide on and
    a handle for one screen to print.

    ``now`` is Unix seconds and arrives as an argument; this package owns
    no clock. ``bot_token`` must not be empty - an empty key still
    produces a perfectly valid HMAC, so a deployment that forgot to
    configure one would accept forgeries from anybody who noticed.
    """
    if not bot_token:
        raise InitDataError("no-token")
    if not raw:
        raise InitDataError("empty")

    fields = _fields(raw)
    keys = tuple(sorted(fields))

    claimed = fields.get(HASH_FIELD, "")
    if not claimed:
        raise InitDataError("no-hash", keys=keys)

    # Constant time. A byte-by-byte comparison leaks the correct prefix,
    # which turns forgery into sixty-four cheap guesses.
    if not hmac.compare_digest(claimed, _digest(fields=fields, bot_token=bot_token)):
        raise InitDataError("bad-signature", keys=keys)

    # --- Past this line the payload is Telegram's -----------------------
    _check_age(fields=fields, keys=keys, now=now, max_age_seconds=max_age_seconds)
    return VerifiedInitData(
        user=_user(fields, keys=keys),
        signed_keys=tuple(key for key in keys if key != HASH_FIELD),
    )


def build_init_data(
    fields: dict[str, str], *, bot_token: str, hash_override: str = ""
) -> str:
    """Sign a payload the way Telegram does.

    Exists for the tests, like ``metaads.build_signed_request``.

    **A test that only uses this proves nothing about the format.** Both
    halves would share any mistake: a helper that leaves ``signature`` out
    of the digest agrees with a parser that leaves it out too, and with
    nothing else. The tests that matter check a frozen vector against a
    second implementation, not against this function.
    """
    digest = hash_override or _digest(fields=fields, bot_token=bot_token)
    parts = [*fields.items(), (HASH_FIELD, digest)]
    return "&".join(
        f"{quote(key, safe='')}={quote(value, safe='')}" for key, value in parts
    )


def _fields(raw: str) -> dict[str, str]:
    """The query string as a mapping, decoded the way every client decodes it.

    ``parse_qsl`` rather than a hand-written split, and the difference
    that matters is ``+``: this reads it as a space, and a parser that
    kept it as a plus would disagree with Telegram about the check string
    for any payload containing one. The reference implementations all use
    this function or its JavaScript equivalent, ``URLSearchParams``, and
    both fold ``+`` to a space.

    ``strict_parsing`` refuses a chunk with no ``=`` rather than dropping
    it, and ``keep_blank_values`` keeps ``start_param=`` as an empty
    string rather than removing a field Telegram signed.

    A repeated key is refused rather than resolved. Which of the two the
    digest covered is not knowable from here, and a rule invented for it
    would be a rule a forger gets to choose between.
    """
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
    """The HMAC Telegram would have written over these fields.

    Every field that arrived except the hash - see :data:`HASH_FIELD` for
    why that sentence has no second half. Sorted by key and joined with
    newlines, which is the format rather than a choice: the sender and the
    receiver have to agree on an order, and alphabetical is the one
    Telegram documents.
    """
    checked = sorted((key, value) for key, value in fields.items() if key != HASH_FIELD)
    check_string = "\n".join(f"{key}={value}" for key, value in checked)

    secret = hmac.new(SECRET_SALT, bot_token.encode("utf-8"), sha256).digest()
    return hmac.new(secret, check_string.encode("utf-8"), sha256).hexdigest()


def _check_age(
    *, fields: dict[str, str], keys: tuple[str, ...], now: int, max_age_seconds: int
) -> None:
    """Refuse a genuine proof that has been lying around.

    A future ``auth_date`` is treated as unreadable rather than as fresh.
    Clocks drift, but a payload dated tomorrow is either a broken client
    or somebody's attempt at an expiry that never arrives, and neither is
    worth a session. The skew is carried so a log can tell a server whose
    clock is wrong from a page somebody left open.
    """
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
    """The ``user`` field, which is JSON inside the query string.

    Absent for a Mini App opened from an inline query or a channel - not
    an error in Telegram's format, and refused here because an account is
    exactly what this function exists to name.
    """
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
    # ``bool`` is an ``int`` in Python, and ``user: {"id": true}`` would
    # otherwise become the account whose id is 1.
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
