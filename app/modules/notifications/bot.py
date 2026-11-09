from collections.abc import Iterator
from contextlib import contextmanager
from urllib.parse import quote

from telegramkit import BotClient

from app.common.config import settings
from app.modules.notifications.exceptions import BotNotConfigured

DEEP_LINK: str = "https://t.me/{username}?start={payload}"
BOT_LINK: str = "https://t.me/{username}"


def is_configured() -> bool:
    return bool(
        settings.telegram_bot_token
        and settings.telegram_webhook_secret
        and settings.telegram_bot_username
    )


def sends_mandatory_notices() -> bool:
    return bool(settings.telegram_mandatory_notices)


def sends_expiry_notices() -> bool:
    return sends_mandatory_notices() or bool(settings.telegram_expiry_notices)


@contextmanager
def bot() -> Iterator[BotClient]:
    if not is_configured():
        raise BotNotConfigured
    client = BotClient(token=settings.telegram_bot_token)
    try:
        yield client
    finally:
        client.close()


def deep_link(*, payload: str) -> str:
    return DEEP_LINK.format(
        username=settings.telegram_bot_username, payload=quote(payload, safe="")
    )


def bot_home() -> str:
    return BOT_LINK.format(username=settings.telegram_bot_username)


def webhook_secret() -> str:
    return str(settings.telegram_webhook_secret)


def bot_token() -> str:
    return str(settings.telegram_bot_token)


def staff_bot_configured() -> bool:
    return bool(
        settings.staff_bot_token
        and settings.staff_bot_webhook_secret
        and settings.staff_bot_username
    )


@contextmanager
def staff_bot() -> Iterator[BotClient]:
    if not staff_bot_configured():
        raise BotNotConfigured
    client = BotClient(token=settings.staff_bot_token)
    try:
        yield client
    finally:
        client.close()


def staff_deep_link(*, payload: str) -> str:
    return DEEP_LINK.format(
        username=settings.staff_bot_username, payload=quote(payload, safe="")
    )


def staff_webhook_secret() -> str:
    return str(settings.staff_bot_webhook_secret)


def support_bot_configured() -> bool:
    return bool(
        settings.support_bot_token
        and settings.support_bot_webhook_secret
        and settings.support_bot_username
    )


@contextmanager
def support_bot() -> Iterator[BotClient]:
    if not support_bot_configured():
        raise BotNotConfigured
    client = BotClient(token=settings.support_bot_token)
    try:
        yield client
    finally:
        client.close()


def support_deep_link(*, payload: str) -> str:
    return DEEP_LINK.format(
        username=settings.support_bot_username, payload=quote(payload, safe="")
    )


def support_bot_home() -> str:
    return BOT_LINK.format(username=settings.support_bot_username)


def support_webhook_secret() -> str:
    return str(settings.support_bot_webhook_secret)


__all__ = [
    "DEEP_LINK",
    "bot",
    "bot_token",
    "deep_link",
    "is_configured",
    "sends_expiry_notices",
    "sends_mandatory_notices",
    "staff_bot",
    "staff_bot_configured",
    "staff_deep_link",
    "staff_webhook_secret",
    "support_bot",
    "support_bot_configured",
    "support_bot_home",
    "support_deep_link",
    "support_webhook_secret",
    "webhook_secret",
]
