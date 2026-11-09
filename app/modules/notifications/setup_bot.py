"""Point a bot's webhook at this deployment, and set its "/" menu.

    uv run python -m app.modules.notifications.setup_bot support
    uv run python -m app.modules.notifications.setup_bot customer

Run once per deployment after the bot's three settings are in .env, and
again whenever SITE_URL or the webhook secret changes. Prints what Telegram
says about the webhook afterwards, so a typo is seen at once.

``customer`` keeps what waits in Telegram's queue - people's messages - and
asks for ``my_chat_member`` too: the bot added to a group or a channel for
leads, or removed from one. Its "/" menu is left as it is.
"""

import sys

from telegramkit import BotClient

from app.common.config import settings
from app.modules.notifications.constants import SUPPORT_BOT_COMMANDS

PATH = "/webhooks/telegram/support/"
CUSTOMER_PATH = "/webhooks/telegram/"
CUSTOMER_UPDATES = ("message", "callback_query", "my_chat_member")


def main() -> int:
    which = sys.argv[1] if len(sys.argv) > 1 else ""
    if which == "customer":
        return customer()
    if which != "support":
        print("usage: python -m app.modules.notifications.setup_bot support|customer")
        return 2
    if not (
        settings.support_bot_token
        and settings.support_bot_webhook_secret
        and settings.support_bot_username
    ):
        print(
            "SUPPORT_BOT_TOKEN, SUPPORT_BOT_WEBHOOK_SECRET, SUPPORT_BOT_USERNAME: set all three"
        )
        return 1
    url = settings.site_url.rstrip("/") + PATH
    with BotClient(token=settings.support_bot_token) as client:
        me = client.get_me()
        if me.username.lower() != settings.support_bot_username.lower():
            print(
                f"the token is @{me.username}, SUPPORT_BOT_USERNAME says @{settings.support_bot_username}"
            )
            return 1
        client.set_webhook(url=url, secret_token=settings.support_bot_webhook_secret)
        client.set_my_commands(commands=SUPPORT_BOT_COMMANDS)
        info = client.get_webhook_info()
    print(f"@{me.username} -> {info.url}")
    print(
        f"pending: {info.pending_update_count}, last error: {info.last_error_message or '-'}"
    )
    return 0


def customer() -> int:
    if not (
        settings.telegram_bot_token
        and settings.telegram_webhook_secret
        and settings.telegram_bot_username
    ):
        print(
            "TELEGRAM_BOT_TOKEN, TELEGRAM_WEBHOOK_SECRET, TELEGRAM_BOT_USERNAME: set all three"
        )
        return 1
    url = settings.site_url.rstrip("/") + CUSTOMER_PATH
    with BotClient(token=settings.telegram_bot_token) as client:
        me = client.get_me()
        if me.username.lower() != settings.telegram_bot_username.lower():
            print(
                f"the token is @{me.username}, TELEGRAM_BOT_USERNAME says @{settings.telegram_bot_username}"
            )
            return 1
        client.set_webhook(
            url=url,
            secret_token=settings.telegram_webhook_secret,
            updates=CUSTOMER_UPDATES,
            drop_pending=False,
        )
        info = client.get_webhook_info()
    print(f"@{me.username} -> {info.url}")
    print(f"allowed: {', '.join(info.allowed_updates) or '-'}")
    print(
        f"pending: {info.pending_update_count}, last error: {info.last_error_message or '-'}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
