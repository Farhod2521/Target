"""Bot API failures, split by what the caller should do about them."""

import re
from typing import Any, Final

_TOKEN_IN_URL: Final = re.compile(r"/bot[^/\s]+")

GONE_DESCRIPTIONS: Final = (
    "chat not found",
    "user not found",
    "chat_id is empty",
    "peer_id_invalid",
    "user is deactivated",
    "bot was blocked by the user",
    "bot was kicked",
    "the group chat was deleted",
)


def scrubbed(text: str) -> str:
    """The same sentence with the bot token taken out of it."""
    return _TOKEN_IN_URL.sub("/bot***", text)


class TelegramError(Exception):
    """Base for anything that went wrong while talking to Telegram."""

    def __init__(self, message: str, *, code: int | None = None) -> None:
        super().__init__(scrubbed(message))
        self.code = code


class TelegramAPIError(TelegramError):
    """Telegram refused the request. Permanent unless stated otherwise."""


class ChatUnreachable(TelegramAPIError):
    """The chat does not exist, or no longer does."""


class BotBlocked(TelegramAPIError):
    """The person blocked the bot, or their account is gone."""


class TelegramTemporaryError(TelegramError):
    """Transient: 5xx, a timeout, or a connection that never opened."""


class TelegramRateLimited(TelegramTemporaryError):
    """Too many messages. ``retry_after`` is Telegram's own figure, in seconds."""

    def __init__(
        self, message: str, *, code: int | None = None, retry_after: int | None = None
    ) -> None:
        super().__init__(message, code=code)
        self.retry_after = retry_after


def translate(*, status: int, payload: dict[str, Any]) -> TelegramError:
    """One refused response as the right class to raise."""
    description = str(payload.get("description") or f"HTTP {status}")
    lowered = description.lower()

    if status == 403 or "bot was blocked" in lowered:
        return BotBlocked(description, code=status)
    if status == 429:
        return TelegramRateLimited(
            description, code=status, retry_after=_retry_after(payload)
        )
    if status >= 500:
        return TelegramTemporaryError(description, code=status)
    if any(phrase in lowered for phrase in GONE_DESCRIPTIONS):
        return ChatUnreachable(description, code=status)
    return TelegramAPIError(description, code=status)


def _retry_after(payload: dict[str, Any]) -> int | None:
    """Telegram's wait, from ``parameters.retry_after``."""
    parameters = payload.get("parameters")
    if not isinstance(parameters, dict):
        return None
    value = parameters.get("retry_after")
    return int(value) if isinstance(value, int) else None


__all__ = [
    "GONE_DESCRIPTIONS",
    "BotBlocked",
    "ChatUnreachable",
    "TelegramAPIError",
    "TelegramError",
    "TelegramRateLimited",
    "TelegramTemporaryError",
    "scrubbed",
    "translate",
]
