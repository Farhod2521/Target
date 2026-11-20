"""The cabinet's places an AI answer may link to, as the person sees them.

The model writes ``[[key]]``; the product swaps it for the place's name in
the reader's language and hands the link to the page. The address comes from
``reverse`` - the one table of routes - so a moved page moves its link too,
and a key that is not here is dropped, never guessed.
"""

import re
from dataclasses import dataclass
from typing import Final

from app.common.config import settings
from app.common.routes import reverse
from app.common.shown import CYRILLIC_UZBEK
from core.written import to_cyrillic

TOKEN: Final = re.compile(r"\[\[([a-z_]+)\]\]")
# A token still being written at the end of a streamed answer: held back so
# the reader never sees half of one.
OPEN_TAIL: Final = re.compile(r"\[\[?[a-z_]*\]?$")
MAX_LINKS: Final = 3


@dataclass(frozen=True, slots=True)
class Place:
    route: str
    names: dict[str, str]
    query: str = ""


PLACES: Final[dict[str, Place]] = {
    "kirish": Place(
        "accounts:login",
        {"uz": "Kirish sahifasi", "ru": "Страница входа", "en": "Sign-in page"},
    ),
    "kirish_yordam": Place(
        "accounts:login",
        {
            "uz": "Kira olmayapsizmi? Yordam beramiz",
            "ru": "Не получается войти? Поможем",
            "en": "Can't sign in? We'll help",
        },
        query="?yordam=chat",
    ),
    "boshqaruv": Place(
        "integrations:connections",
        {
            "uz": "Sozlash → Boshqaruv",
            "ru": "Настройка → Управление",
            "en": "Setup → Manage",
        },
    ),
    "obuna": Place(
        "billing:plans",
        {
            "uz": "Sozlash → Obuna va to'lov",
            "ru": "Настройка → Подписка и оплата",
            "en": "Setup → Subscription and payment",
        },
    ),
    "tolovlar": Place(
        "billing:history",
        {
            "uz": "Barcha to'lovlar va obuna tarixi",
            "ru": "Все платежи и история подписки",
            "en": "All payments and subscription history",
        },
    ),
    "profil": Place(
        "account:home",
        {
            "uz": "Sozlash → Profil",
            "ru": "Настройка → Профиль",
            "en": "Setup → Profile",
        },
    ),
    "bildirishnomalar": Place(
        "notifications:settings",
        {
            "uz": "Sozlash → Bildirishnomalar",
            "ru": "Настройка → Уведомления",
            "en": "Setup → Notifications",
        },
    ),
    "biznes": Place(
        "businesses:profile",
        {
            "uz": "Sozlash → Biznes profili",
            "ru": "Настройка → Профиль бизнеса",
            "en": "Setup → Business profile",
        },
    ),
    "dashboard": Place(
        "metrics:dashboard", {"uz": "Dashboard", "ru": "Дашборд", "en": "Dashboard"}
    ),
    "tayyorgarlik": Place(
        "onboarding:start", {"uz": "Tayyorgarlik", "ru": "Подготовка", "en": "Setup"}
    ),
    "reklama": Place("ads:campaigns", {"uz": "Reklama", "ru": "Реклама", "en": "Ads"}),
    "reklama_berish": Place(
        "ads:launch_start",
        {"uz": "Reklama berish", "ru": "Запустить рекламу", "en": "Start an ad"},
    ),
    "lidlar": Place(
        "leads:list",
        {"uz": "CRM & Lidlar", "ru": "CRM и лиды", "en": "CRM & Leads"},
    ),
    "crm": Place(
        "crm:board",
        {
            "uz": "CRM & Lidlar → CRM",
            "ru": "CRM и лиды → CRM",
            "en": "CRM & Leads → CRM",
        },
    ),
    "crm_sozlamalar": Place(
        "crm:settings",
        {
            "uz": "CRM & Lidlar → Sozlamalar",
            "ru": "CRM и лиды → Настройки",
            "en": "CRM & Leads → Settings",
        },
    ),
    "amallar": Place(
        "actions:home", {"uz": "Amallar", "ru": "Действия", "en": "Actions"}
    ),
    "daromad": Place(
        "referrals:wallet", {"uz": "Daromad", "ru": "Доход", "en": "Earnings"}
    ),
    "darsliklar": Place(
        "tutorials:list", {"uz": "Darsliklar", "ru": "Уроки", "en": "Lessons"}
    ),
}


@dataclass(frozen=True, slots=True)
class Linked:
    """An answer with its tokens swapped for names, and the links it named."""

    text: str
    links: list[dict[str, str]]


def name_of(key: str, language: str) -> str:
    """The place's name in this language (a ``Written.key``): Uzbek in
    Cyrillic is its Latin name transliterated."""
    place = PLACES[key]
    if language == CYRILLIC_UZBEK:
        return to_cyrillic(place.names["uz"])
    return place.names.get(language) or place.names["uz"]


def url_of(key: str) -> str:
    """The full address: the page may sit on another host than the cabinet."""
    place = PLACES[key]
    return f"{settings.site_url}{reverse(place.route)}{place.query}"


def linked(text: str, *, language: str, done: bool = True) -> Linked:
    """``[[key]]`` becomes «the place's name»; each known place, once, is a
    link. An unknown key leaves nothing. While streaming (``done=False``) an
    unfinished token at the end is held back."""
    if not done:
        text = OPEN_TAIL.sub("", text)
    links: list[dict[str, str]] = []

    def swap(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in PLACES:
            return ""
        title = name_of(key, language)
        if len(links) < MAX_LINKS and all(item["key"] != key for item in links):
            links.append({"key": key, "title": title, "url": url_of(key)})
        return f"«{title}»"

    swapped = TOKEN.sub(swap, text)
    # «[[key]]» written inside the model's own brackets: one pair is enough.
    swapped = swapped.replace("««", "«").replace("»»", "»")
    return Linked(text=swapped, links=links)


def place_html(rendered: str, *, language: str) -> str:
    """Rendered HTML with each ``[[key]]`` turned into an anchor named for
    the place - for pages that draw the answer's HTML as it is."""
    import html as markup

    def anchor(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in PLACES:
            return ""
        return (
            f'«<a href="{markup.escape(url_of(key))}" class="underline">'
            f"{markup.escape(name_of(key, language))}</a>»"
        )

    drawn = TOKEN.sub(anchor, rendered)
    return drawn.replace("««", "«").replace("»»", "»")


def held_back(text: str) -> str:
    """A streamed answer without the unfinished token at its end."""
    return OPEN_TAIL.sub("", text)


def keys_line() -> str:
    """The keys as the prompt lists them: ``[[key]]`` - its Uzbek name."""
    return "\n".join(
        f"- `[[{key}]]` - {place.names['uz']}" for key, place in PLACES.items()
    )


__all__ = [
    "MAX_LINKS",
    "PLACES",
    "Linked",
    "held_back",
    "keys_line",
    "linked",
    "name_of",
    "place_html",
    "url_of",
]
