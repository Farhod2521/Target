"""Point a bot's webhook at this deployment, and set its "/" menu.

    uv run python -m app.modules.notifications.setup_bot support

Run once per deployment after the bot's three settings are in .env, and
again whenever SITE_URL or the webhook secret changes. Prints what Telegram
says about the webhook afterwards, so a typo is seen at once.
"""

import sys

from telegramkit import BotClient

from app.common.config import settings
from app.modules.notifications.constants import SUPPORT_BOT_COMMANDS

PATH = "/webhooks/telegram/support/"


def main() -> int:
    which = sys.argv[1] if len(sys.argv) > 1 else ""
    if which != "support":
        print("usage: python -m app.modules.notifications.setup_bot support")
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


if __name__ == "__main__":
    sys.exit(main())
