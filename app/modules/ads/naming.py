import re
from collections.abc import Collection, Mapping, Sequence
from datetime import datetime
from typing import Any, Final
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.common import timezone
from app.common.presets import goals_for
from app.modules.ads import draft as draft_field
from app.modules.ads import geo as geo_field
from app.modules.ads.constants import (
    LAUNCH_NAME_MAX,
    LEAD_FORM_NAME,
    LEAD_FORM_NAME_MAX,
    DraftSection,
    TargetingMode,
)
from app.modules.ads.models import CampaignLaunch
from app.modules.ads.selectors.budget_level import held_by_campaign
from app.modules.businesses.models import Business
from core.targeting.describe import describe
from core.targeting.modes import is_automatic

MAX_NAME: Final = LAUNCH_NAME_MAX
SEPARATOR: Final = " · "
ELLIPSIS: Final = "…"
MIN_BUSINESS: Final = 10
ADSET: Final = "auditoriya"
CREATIVE: Final = "kreativ"
AD: Final = "reklama"
FORM: Final = "lidlar"
MODE_WORDS: Final[dict[str, str]] = {
    TargetingMode.BROAD: "Keng",
    TargetingMode.AUTOMATIC: "Avtomatik",
}
STAMP: Final = "%d.%m %H:%M"
_PARSE_YEAR: Final = 2024

# What Ads Manager shows: «Sahifa - Calls - ABO - 17.11.2026 - 17:18» for the
# campaign, the audience for the ad set and «#1» for the ad.
DASH: Final = " - "
DAY: Final = "%d.%m.%Y"
TIME: Final = "%H:%M"
PLACES_SHOWN: Final = 2
PLACE_JOIN: Final = ", "
AGE_FLOOR: Final = 18
AGE_CEILING: Final = 65
LANGUAGES: Final = ("uz", "ru", "en")
GOAL_WORDS: Final[dict[str, dict[str, str]]] = {
    "leads": {"uz": "Lid", "ru": "Лиды", "en": "Leads"},
    "messages": {"uz": "Xabar", "ru": "Сообщения", "en": "Messages"},
    "calls": {"uz": "Qo'ng'iroq", "ru": "Звонки", "en": "Calls"},
    "views": {"uz": "Ko'rish", "ru": "Просмотры", "en": "Views"},
    "traffic": {"uz": "Trafik", "ru": "Трафик", "en": "Traffic"},
    "profile_visits": {"uz": "Profil", "ru": "Профиль", "en": "Profile"},
    "site_leads": {"uz": "Sayt lid", "ru": "Лиды сайт", "en": "Site leads"},
    "store_visits": {"uz": "Do'kon", "ru": "Магазин", "en": "Store"},
    "sales": {"uz": "Sotuv", "ru": "Продажи", "en": "Sales"},
    "awareness": {"uz": "Tanilish", "ru": "Узнаваемость", "en": "Awareness"},
}
AUDIENCE_WORDS: Final[dict[str, dict[str, str]]] = {
    "everyone": {"uz": "Hamma", "ru": "Все", "en": "All"},
    "female": {"uz": "Ayol", "ru": "Жен", "en": "Women"},
    "male": {"uz": "Erkak", "ru": "Муж", "en": "Men"},
    "interests": {"uz": "Qiziqish", "ru": "Интересы", "en": "Interests"},
    "lookalike": {"uz": "O'xshash", "ru": "Похожие", "en": "Lookalike"},
    "custom": {"uz": "O'z", "ru": "Свои", "en": "Custom"},
}
ADVANTAGE: Final = "Adv+"
_DASH_STAMP: Final = re.compile(r"^(?P<head>.+?) - \d{2}\.\d{2}\.\d{4} - \d{2}:\d{2}$")


def campaign_name(*, launch: CampaignLaunch, business: Business) -> str:
    """This launch's campaign, stamped when the launch was opened."""
    page = launch.page.name if launch.page is not None else ""
    return _campaign(
        launch=launch, business=business, page_name=page, at=launch.created_at
    )


def goal_campaign_name(
    *,
    launch: CampaignLaunch,
    business: Business,
    page_name: str,
    at: datetime | None = None,
) -> str:
    """The campaign a page's launches for one goal share, stamped as it opens."""
    return _campaign(
        launch=launch,
        business=business,
        page_name=page_name,
        at=at or timezone.now(),
    )


def adset_name(
    *,
    launch: CampaignLaunch,
    business: Business,
    position: int = 0,
    of: int = 1,
    lookalikes: Collection[str] = (),
) -> str:
    """Who the ad set is shown to, in the owner's language; «#2» on a second group."""
    name = audience_name(
        targeting=launch.targeting,
        chosen=draft_field.chosen(launch.draft, DraftSection.AUDIENCE),
        language=_language(launch),
        lookalikes=lookalikes,
    )
    return f"{name} #{position + 1}"[:MAX_NAME] if of > 1 else name[:MAX_NAME]


def audience_name(
    *,
    targeting: Any,
    chosen: Any,
    language: str,
    lookalikes: Collection[str] = (),
) -> str:
    """Only what was chosen; the gender always, «Hamma» when it was not."""
    spec: Mapping[str, Any] = targeting if isinstance(targeting, Mapping) else {}
    sketch = describe(spec)
    included = _ids(spec.get("custom_audiences"))
    parts = [
        _ages(sketch.age_min, sketch.age_max),
        _word(sketch.genders or "everyone", language),
        _places(chosen) or _radius(sketch.geo, sketch.radius),
        _word("interests", language) if sketch.interests else "",
        _word("lookalike", language) if included & set(lookalikes) else "",
        _word("custom", language) if included - set(lookalikes) else "",
        ADVANTAGE if is_automatic(spec) else "",
    ]
    return DASH.join(part for part in parts if part)


def creative_name(*, launch: CampaignLaunch, business: Business, position: int) -> str:
    return _named(launch=launch, business=business, tail=_counted(CREATIVE, position))


def ad_name(*, launch: CampaignLaunch, business: Business, position: int = 0) -> str:
    return f"#{position + 1}"


def form_name(*, launch: CampaignLaunch, business: Business, attempt: int = 1) -> str:
    suffix = f" ({attempt})" if attempt > 1 else ""
    chosen = str(launch.answers.get(LEAD_FORM_NAME) or "").strip()
    if chosen:
        return f"{chosen}{suffix}"[:LEAD_FORM_NAME_MAX]
    return _named(launch=launch, business=business, tail=f"{FORM}{suffix}")


def short_name(name: str) -> str:
    stamped = _DASH_STAMP.match(name)
    if stamped:
        return stamped.group("head")
    parts = [part for part in name.split(SEPARATOR) if part]
    if len(parts) < 2 or not _is_stamp(parts[-1]):
        return name
    kept = [part for part in parts[:-1] if part not in MODE_WORDS.values()]
    return SEPARATOR.join(kept) if kept else parts[-1]


def _is_stamp(part: str) -> bool:
    try:
        datetime.strptime(f"{part} {_PARSE_YEAR}", f"{STAMP} %Y")
    except ValueError:
        return False
    return True


def _counted(word: str, position: int) -> str:
    return f"{word} {position + 1}"


def _named(*, launch: CampaignLaunch, business: Business, tail: str) -> str:
    fixed = SEPARATOR.join(
        part
        for part in (
            _goal(launch, business),
            _mode(launch),
            _when(launch, business),
            tail,
        )
        if part
    )
    return _fitted(house=(business.name or "").strip(), fixed=fixed)


def _fitted(*, house: str, fixed: str, separator: str = SEPARATOR) -> str:
    if not fixed:
        return house[:MAX_NAME]
    if not house:
        return fixed[:MAX_NAME]
    room = MAX_NAME - len(fixed) - len(separator)
    if room >= len(house):
        return f"{house}{separator}{fixed}"
    if room >= MIN_BUSINESS:
        return f"{house[: room - 1].rstrip()}{ELLIPSIS}{separator}{fixed}"
    return fixed[:MAX_NAME]


def _campaign(
    *,
    launch: CampaignLaunch,
    business: Business,
    page_name: str,
    at: datetime | None,
) -> str:
    level = "CBO" if held_by_campaign(launch=launch) else "ABO"
    parts = [_goal_word(launch, _language(launch)), level]
    if at is not None:
        local = timezone.localtime(at, _zone(business.timezone))
        parts += [local.strftime(DAY), local.strftime(TIME)]
    house = page_name.strip() or (business.name or "").strip()
    return _fitted(
        house=house, fixed=DASH.join(part for part in parts if part), separator=DASH
    )


def _goal_word(launch: CampaignLaunch, language: str) -> str:
    words = GOAL_WORDS.get(str(launch.answers.get("goal") or ""))
    return words[language] if words else ""


def _language(launch: CampaignLaunch) -> str:
    owner = launch.owner
    language = owner.language if owner is not None else ""
    return language if language in LANGUAGES else "uz"


def _word(key: str, language: str) -> str:
    words = AUDIENCE_WORDS[key]
    return words.get(language) or words["uz"]


def _ages(low: int | None, high: int | None) -> str:
    low = low if low and low > AGE_FLOOR else None
    high = high if high and high < AGE_CEILING else None
    if low and high:
        return f"{low}-{high}"
    if low:
        return f"{low}+"
    if high:
        return f"{AGE_FLOOR}-{high}"
    return ""


def _places(chosen: Any) -> str:
    """The places a person picked: two by name, the rest counted."""
    if not isinstance(chosen, dict) or not isinstance(
        chosen.get(geo_field.GEO_KEY), dict
    ):
        return ""
    choice = geo_field.to_choice(chosen)
    if choice.mode == "country" and choice.origin != "chosen":
        return ""
    names = [place.name for place in choice.places if place.name]
    if not names:
        return ""
    shown = PLACE_JOIN.join(names[:PLACES_SHOWN])
    rest = len(names) - PLACES_SHOWN
    return f"{shown} +{rest}" if rest > 0 else shown


def _radius(geo: str, radius: int | None) -> str:
    return f"{radius} km" if geo == "around" and radius else ""


def _ids(value: Any) -> set[str]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        return set()
    return {
        str(item.get("id"))
        for item in value
        if isinstance(item, Mapping) and item.get("id")
    }


def _goal(launch: CampaignLaunch, business: Business) -> str:
    goal = str(launch.answers.get("goal", ""))
    if not goal or not business.category:
        return ""
    for preset in goals_for(provider=launch.provider, category=business.category):
        if preset.goal == goal:
            return preset.label
    return ""


def _mode(launch: CampaignLaunch) -> str:
    audience: Any = draft_field.chosen(launch.draft, DraftSection.AUDIENCE)
    if not isinstance(audience, dict):
        return ""
    return MODE_WORDS.get(str(audience.get("targeting_mode") or ""), "")


def _when(launch: CampaignLaunch, business: Business) -> str:
    if launch.created_at is None:
        return ""
    return timezone.localtime(launch.created_at, _zone(business.timezone)).strftime(
        STAMP
    )


def _zone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


__all__ = [
    "AD",
    "ADSET",
    "CREATIVE",
    "ELLIPSIS",
    "FORM",
    "MAX_NAME",
    "SEPARATOR",
    "ad_name",
    "adset_name",
    "audience_name",
    "campaign_name",
    "creative_name",
    "form_name",
    "goal_campaign_name",
    "short_name",
]
