from datetime import datetime
from typing import Any, Final
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.common import timezone
from app.common.presets import goals_for
from app.modules.ads import draft as draft_field
from app.modules.ads.constants import (
    LAUNCH_NAME_MAX,
    LEAD_FORM_NAME,
    LEAD_FORM_NAME_MAX,
    DraftSection,
    TargetingMode,
)
from app.modules.ads.models import CampaignLaunch
from app.modules.businesses.models import Business

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


def campaign_name(*, launch: CampaignLaunch, business: Business) -> str:
    return _named(launch=launch, business=business, tail="")


def goal_campaign_name(
    *, launch: CampaignLaunch, business: Business, number: int
) -> str:
    goal = _goal(launch, business)
    fixed = f"{goal} #{number}" if goal else f"#{number}"
    return _fitted(house=(business.name or "").strip(), fixed=fixed)


def adset_name(
    *, launch: CampaignLaunch, business: Business, position: int = 0, of: int = 1
) -> str:
    tail = _counted(ADSET, position) if of > 1 else ADSET
    return _named(launch=launch, business=business, tail=tail)


def creative_name(*, launch: CampaignLaunch, business: Business, position: int) -> str:
    return _named(launch=launch, business=business, tail=_counted(CREATIVE, position))


def ad_name(*, launch: CampaignLaunch, business: Business, position: int = 0) -> str:
    return _named(launch=launch, business=business, tail=_counted(AD, position))


def form_name(*, launch: CampaignLaunch, business: Business, attempt: int = 1) -> str:
    suffix = f" ({attempt})" if attempt > 1 else ""
    chosen = str(launch.answers.get(LEAD_FORM_NAME) or "").strip()
    if chosen:
        return f"{chosen}{suffix}"[:LEAD_FORM_NAME_MAX]
    return _named(launch=launch, business=business, tail=f"{FORM}{suffix}")


def short_name(name: str) -> str:
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


def _fitted(*, house: str, fixed: str) -> str:
    if not fixed:
        return house[:MAX_NAME]
    if not house:
        return fixed[:MAX_NAME]
    room = MAX_NAME - len(fixed) - len(SEPARATOR)
    if room >= len(house):
        return f"{house}{SEPARATOR}{fixed}"
    if room >= MIN_BUSINESS:
        return f"{house[: room - 1].rstrip()}{ELLIPSIS}{SEPARATOR}{fixed}"
    return fixed[:MAX_NAME]


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
    "campaign_name",
    "creative_name",
    "form_name",
    "short_name",
]
