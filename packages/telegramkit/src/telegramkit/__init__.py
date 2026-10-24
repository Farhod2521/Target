"""Telegram Bot API — notifications, button presses, and a Mini App's proof.

Deliberately not built like ``metaads``. There is no port, no adapter and
no registry: those exist because a second ad platform is coming and the
domain must not learn its name. No second chat platform is coming, and a
``ChatPort`` with one implementation is an abstraction that costs a file
and buys a diagram.

What it does keep from ``metaads`` is the part that is about correctness
rather than about platforms: timeouts on both halves, failures split by
what the caller should do about them, and the credential kept out of every
string that can reach a log.

``webapp`` is the third half and the odd one out: no HTTP at all, just
the HMAC that says a page opened inside Telegram belongs to the account it
claims. It is here rather than in the product because the derivation - the
salt, the field order, the one field the digest does not cover - is
Telegram's format, and a product that learned it would have learned a
provider's shape.

Nothing here reads configuration or the clock. Both arrive as arguments.
"""

from telegramkit.client import (
    API_BASE_URL,
    DOCUMENT_MAX_BYTES,
    MESSAGE_MAX_CHARS,
    PHOTO_MAX_BYTES,
    BotClient,
    message_units,
)
from telegramkit.errors import (
    BotBlocked,
    ChatUnreachable,
    TelegramAPIError,
    TelegramError,
    TelegramRateLimited,
    TelegramTemporaryError,
    scrubbed,
)
from telegramkit.models import BotIdentity, Button, SentMessage, WebhookInfo
from telegramkit.updates import (
    CALLBACK_DATA_MAX_BYTES,
    ButtonPress,
    Command,
    OtherMessage,
    Sender,
    TextMessage,
    Update,
    read_update,
    secret_matches,
)
from telegramkit.webapp import (
    DEFAULT_MAX_AGE_SECONDS,
    InitDataError,
    InitDataExpired,
    VerifiedInitData,
    build_init_data,
    parse_init_data,
)

__all__ = [
    "API_BASE_URL",
    "CALLBACK_DATA_MAX_BYTES",
    "DEFAULT_MAX_AGE_SECONDS",
    "DOCUMENT_MAX_BYTES",
    "MESSAGE_MAX_CHARS",
    "PHOTO_MAX_BYTES",
    "BotBlocked",
    "BotClient",
    "BotIdentity",
    "Button",
    "ButtonPress",
    "ChatUnreachable",
    "Command",
    "InitDataError",
    "InitDataExpired",
    "OtherMessage",
    "Sender",
    "SentMessage",
    "TelegramAPIError",
    "TelegramError",
    "TelegramRateLimited",
    "TelegramTemporaryError",
    "TextMessage",
    "Update",
    "VerifiedInitData",
    "WebhookInfo",
    "build_init_data",
    "message_units",
    "parse_init_data",
    "read_update",
    "scrubbed",
    "secret_matches",
]
