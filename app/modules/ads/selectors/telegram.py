"""«Telegramga o'tsin»: a visit bought from Meta, whose tap opens Telegram.

Meta has no Telegram goal. The advert is a link advert of the ``traffic``
goal, optimised for the tap on the link because nothing can be counted inside
Telegram. So the first step offers one more goal, the launch keeps ``traffic``
with ``link_kind`` beside it, and everything after the plan builds a visit.
"""

import re
from dataclasses import replace
from typing import Final
from urllib.parse import parse_qs, urlparse

from app.modules.ads.models import CampaignLaunch
from core.targeting import Preset

TELEGRAM_GOAL: Final = "telegram"
# The goal Meta is asked for.
BOUGHT_AS: Final = "traffic"
# The answer that says where the link of a visit leads; ``""`` is a site.
LINK_KIND: Final = "link_kind"
TELEGRAM_LABEL: Final = "Telegramga o'tsin"
# What the copy prompts and the copy check are told the button does.
TELEGRAM_BUTTON: Final = "telegram"
NOT_TELEGRAM: Final = "Telegram havolasini yoki @username yozing. Masalan: @kanalingiz yoki t.me/kanalingiz"

TELEGRAM_HOSTS: Final = frozenset({"t.me", "telegram.me", "telegram.dog"})
# A public name: a letter first, then letters, digits and underscores.
_NAME: Final = re.compile(r"^[A-Za-z][A-Za-z0-9_]{3,31}$")
# What follows the host: a name, an invite (+code, joinchat/code), a post or a bot's start.
_PATH: Final = re.compile(
    r"^(\+[\w-]{8,}|joinchat/[\w-]{8,}|[A-Za-z][A-Za-z0-9_]{3,31}(/[\w-]+)*)$"
)
_QUERY: Final = re.compile(r"^[\w=&%.+-]{0,256}$")


def telegram_link(raw: str) -> str:
    """What was typed as ``https://t.me/...``, or ``""`` when it is not Telegram.

    ``@kanal``, ``kanal``, ``t.me/kanal``, ``https://telegram.me/kanal``, an
    invite (``t.me/+AbCd...``), a bot's start link and ``tg://resolve?domain=``
    are all one address to the person tapping, so all are taken.
    """
    typed = raw.strip()
    if not typed:
        return ""
    if typed.startswith("@"):
        typed = typed[1:]
    if _NAME.match(typed):
        return f"https://t.me/{typed}"
    if typed.lower().startswith("tg://"):
        asked = urlparse(typed)
        name = (parse_qs(asked.query).get("domain") or [""])[0]
        return f"https://t.me/{name}" if _NAME.match(name) else ""
    if "://" not in typed:
        typed = f"https://{typed}"
    parsed = urlparse(typed)
    host = (parsed.hostname or "").lower().removeprefix("www.")
    path = parsed.path.strip("/")
    if parsed.scheme not in {"http", "https"} or host not in TELEGRAM_HOSTS:
        return ""
    if path.startswith("s/"):
        # The channel's web preview: the channel itself is what should open.
        path = path[2:]
    if not _PATH.match(path) or not _QUERY.match(parsed.query):
        return ""
    return f"https://t.me/{path}" + (f"?{parsed.query}" if parsed.query else "")


def is_telegram(launch: CampaignLaunch) -> bool:
    """Whether this launch's visit leads to Telegram."""
    answers = launch.answers or {}
    return (
        str(answers.get("goal") or "") == BOUGHT_AS
        and str(answers.get(LINK_KIND) or "") == TELEGRAM_GOAL
    )


def bought_goal(goal: str) -> str:
    """The catalogue's goal behind what the first step calls it."""
    return BOUGHT_AS if goal == TELEGRAM_GOAL else goal


def shown_goal(launch: CampaignLaunch) -> str:
    """The launch's goal as the first step names it."""
    if is_telegram(launch):
        return TELEGRAM_GOAL
    return str((launch.answers or {}).get("goal") or "")


def with_telegram(offered: tuple[Preset, ...]) -> tuple[Preset, ...]:
    """The goals with «Telegramga o'tsin» after the visit it is bought as."""
    found: list[Preset] = []
    for preset in offered:
        found.append(preset)
        if preset.goal == BOUGHT_AS and preset.provider == "meta":
            found.append(replace(preset, goal=TELEGRAM_GOAL, label=TELEGRAM_LABEL))
    return tuple(found)


__all__ = [
    "BOUGHT_AS",
    "LINK_KIND",
    "NOT_TELEGRAM",
    "TELEGRAM_BUTTON",
    "TELEGRAM_GOAL",
    "TELEGRAM_LABEL",
    "bought_goal",
    "is_telegram",
    "shown_goal",
    "telegram_link",
    "with_telegram",
]
