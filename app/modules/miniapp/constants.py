from typing import Final

INIT_DATA_FIELD: Final = "init_data"
NEXT_FIELD: Final = "next"
INIT_DATA_MAX_AGE_SECONDS: Final = 24 * 60 * 60
SESSION_AGE_SECONDS: Final = INIT_DATA_MAX_AGE_SECONDS
TELEGRAM_FRAME_ANCESTORS: Final = (
    "https://web.telegram.org",
    "https://webk.telegram.org",
    "https://webz.telegram.org",
)
BRIDGE_SCRIPT: Final = "https://telegram.org/js/telegram-web-app.js"
SESSION_FLAG: Final = "in_telegram"
TELEGRAM_COOKIE: Final = "tg_app"
TELEGRAM_COOKIE_MAX_AGE: Final = 180 * 24 * 60 * 60
__all__ = [
    "BRIDGE_SCRIPT",
    "INIT_DATA_FIELD",
    "INIT_DATA_MAX_AGE_SECONDS",
    "NEXT_FIELD",
    "SESSION_AGE_SECONDS",
    "SESSION_FLAG",
    "TELEGRAM_COOKIE",
    "TELEGRAM_COOKIE_MAX_AGE",
    "TELEGRAM_FRAME_ANCESTORS",
]
