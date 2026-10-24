"""Bot API failures, split by what the caller should do about them.

Four questions, four classes. Is this chat gone for good, so the link
should be switched off? Is this a limit that will pass on its own? Is it
Telegram having a bad minute? Or is it our request being wrong?

The split matters because only the first answer changes stored state. A
product that switched a notification channel off on a rate limit would
punish its busiest accounts, and one that left it on after the bot was
blocked would keep paying for messages nobody can receive.

**The token never appears in any of these.** Telegram puts it in the URL
path - ``/bot<token>/sendMessage`` - so an exception carrying the URL
carries the credential, and an exception is the one string that reliably
reaches a log, a Sentry issue and a traceback in CI. :func:`scrubbed` is
what every message here goes through.
"""

import re
from typing import Any, Final

# ``/bot123456:ABC-DEF/`` in a URL. Replaced whole rather than partially:
# a token with its middle stars out is still a token whose length and
# bot id are public, and neither is worth the risk of the pattern being
# a character short one day.
_TOKEN_IN_URL: Final = re.compile(r"/bot[^/\s]+")

# What Telegram says when the chat is beyond reach for good. Matched on
# the description because the status code does not tell these apart from
# an ordinary bad request: a malformed ``parse_mode`` and a deleted
# account are both 400, and only one of them means "stop trying".
#
# Lowercase, and compared against a lowercased description. Telegram's
# wording is stable but its capitalisation is not.
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
    """The same sentence with the bot token taken out of it.

    Applied to everything that becomes an exception message or a log line.
    Not a courtesy: the token is the whole credential - anyone holding it
    can read every message the bot receives and send as it - and unlike an
    API key in a header it travels in the URL, which is the part of a
    request that gets printed.
    """
    return _TOKEN_IN_URL.sub("/bot***", text)


class TelegramError(Exception):
    """Base for anything that went wrong while talking to Telegram."""

    def __init__(self, message: str, *, code: int | None = None) -> None:
        super().__init__(scrubbed(message))
        self.code = code


class TelegramAPIError(TelegramError):
    """Telegram refused the request. Permanent unless stated otherwise.

    The ordinary case is our own mistake: a malformed keyboard, a message
    over the length limit, an edit that changes nothing. None of them is
    fixed by sending the same thing again.
    """


class ChatUnreachable(TelegramAPIError):
    """The chat does not exist, or no longer does.

    Distinguished from every other 400 because it is the only one that
    should stop the product writing to this chat again. See
    :data:`GONE_DESCRIPTIONS` for why the code alone cannot say so.
    """


class BotBlocked(TelegramAPIError):
    """The person blocked the bot, or their account is gone.

    Telegram's own way of saying "this person opted out", and the product
    treats it as exactly that: the link is switched off and nothing is
    retried. A notification channel somebody blocked is not a delivery
    problem to solve.
    """


class TelegramTemporaryError(TelegramError):
    """Transient: 5xx, a timeout, or a connection that never opened.

    Nothing in this product retries one. The three messages it sends are
    each visible in the cabinet as well, so a dropped one costs a person a
    notification and never a fact.
    """


class TelegramRateLimited(TelegramTemporaryError):
    """Too many messages. ``retry_after`` is Telegram's own figure, in seconds.

    Carried even though nothing waits on it, because the number is the
    only evidence of *how far* over the limit a deployment went - and a
    log line that says "429" and nothing else cannot tell a busy minute
    from a broken loop.
    """

    def __init__(
        self, message: str, *, code: int | None = None, retry_after: int | None = None
    ) -> None:
        super().__init__(message, code=code)
        self.retry_after = retry_after


def translate(*, status: int, payload: dict[str, Any]) -> TelegramError:
    """One refused response as the right class to raise.

    The class is the decision, not the status: everything above this
    package branches on the type, so a new Telegram behaviour is a line
    here rather than a change in a service.
    """
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
