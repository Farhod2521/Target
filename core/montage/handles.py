"""Where a viewer is sent: a Telegram or Instagram username, however typed.

People paste a username, an ``@name``, a bare address or a full link with
tracking on it. Each comes back as the plain username, or ``""`` when
there is none to find.
"""

import re
from typing import Final
from urllib.parse import urlparse

from core.leads.ending import telegram_username

__all__ = ["instagram_username", "telegram_username"]

INSTAGRAM_HOSTS: Final = frozenset({"instagram.com", "instagr.am"})
# Letters, digits, dots and underscores, at most thirty - Instagram's rule.
_INSTAGRAM: Final = re.compile(r"^(?!.*\.\.)(?!\.)[A-Za-z0-9._]{1,30}(?<!\.)$")


def instagram_username(raw: str) -> str:
    """The username in what somebody typed, or ``""`` if there is none.

    ``dokon``, ``@dokon``, ``instagram.com/dokon`` and
    ``https://www.instagram.com/dokon/?igsh=abc`` are all ``dokon``.
    """
    text = raw.strip()
    if not text:
        return ""
    if "/" in text:
        address = text if "://" in text else f"https://{text}"
        parsed = urlparse(address)
        host = (parsed.hostname or "").lower().removeprefix("www.").removeprefix("m.")
        if host not in INSTAGRAM_HOSTS:
            return ""
        text = parsed.path.strip("/").split("/")[0]
    text = text.removeprefix("@")
    return text.lower() if _INSTAGRAM.fullmatch(text) else ""


def split_handle(raw: str) -> tuple[str, str]:
    """A handle typed when one box took either network: ``(telegram, instagram)``.

    An Instagram address goes to Instagram. A bare name Telegram accepts
    stays Telegram's - it was the first network named. A bare name only
    Instagram accepts (a dot, or under five letters) goes to Instagram.
    Anything else is kept in Telegram's place as typed, for a person to fix.
    """
    text = raw.strip()
    host = text.lower().split("://")[-1].removeprefix("www.").removeprefix("m.")
    if host.startswith(tuple(INSTAGRAM_HOSTS)):
        return "", instagram_username(text)
    if telegram := telegram_username(text):
        return telegram, ""
    if instagram := instagram_username(text):
        return "", instagram
    return text, ""
