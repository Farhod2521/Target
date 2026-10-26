"""Where the tap goes: an address, a number, or a conversation."""

import re
from urllib.parse import urlparse

from metaads.specs import is_external

from app.modules.ads.inputs import Problems
from core.targeting import dialable, is_local

URL_MAX = 1000
_HOST = re.compile(
    r"^(?=.{1,253}$)([a-z0-9-]{1,63}\.)+[a-z]{2,63}$|^\d{1,3}(\.\d{1,3}){3}$"
)

NOT_DIALABLE = "Bu raqamga qo'ng'iroq qilib bo'lmaydi — qaytadan yozing."
NOT_LOCAL = (
    "Raqam boshqa davlatniki — reklama ko'rsatiladigan davlatning raqamini yozing."
)
NOT_OWN_SITE = "Facebook yoki Instagram sahifasi emas, o'z saytingiz kerak."


def web_address(raw: str) -> str:
    """What was typed, with a scheme, or ``""`` when it is not an address."""
    url = raw.strip()
    if not url:
        return ""
    if "://" not in url:
        url = f"https://{url}"
    if len(url) > URL_MAX:
        return ""
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"} or not _HOST.match(host):
        return ""
    return url


def own_site(raw: str, *, problems: Problems, field: str) -> str:
    """A link that leaves Meta, or ``""`` after adding a problem."""
    url = web_address(raw)
    if not url:
        problems.add(field, "Sayt manzilini to'liq yozing.")
        return ""
    if not is_external(url):
        problems.add(field, NOT_OWN_SITE)
        return ""
    return url


def phone_in(raw: str, *, region: str, problems: Problems, field: str) -> str:
    """A number that can be rung in the ad's own country, or ``""``."""
    number = dialable(raw=raw.strip(), region=region)
    if not number:
        problems.add(field, NOT_DIALABLE)
        return ""
    if not is_local(number=number, region=region):
        problems.add(field, NOT_LOCAL)
        return ""
    return number


__all__ = ["NOT_OWN_SITE", "own_site", "phone_in", "web_address"]
