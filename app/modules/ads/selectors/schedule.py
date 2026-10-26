"""When a launch starts and stops, what its objects are called, and how many it holds."""

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta, tzinfo
from typing import Final
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.common.config import settings
from app.modules.ads.constants import (
    DEFAULT_ADSETS_PER_CAMPAIGN,
    MAX_ADS_PER_CAMPAIGN,
    START_LEAD_MINUTES,
)
from app.modules.ads.models import CampaignLaunch, LaunchCreative
from app.modules.ads.naming import ad_name, campaign_name
from app.modules.businesses.models import Business

MIN_RUN: Final = timedelta(hours=24, minutes=10)


@dataclass(frozen=True, slots=True)
class StartDay:
    day: date | None
    hour: time | None
    starts_early: bool


def start_at(*, launch: CampaignLaunch, now: datetime) -> datetime | None:
    """The moment delivery may begin, or ``None`` for "as soon as it is on"."""
    if launch.start_date is None or launch.ad_account is None:
        return None
    moment = _midnight(launch=launch)
    if moment is None or moment <= now + timedelta(minutes=START_LEAD_MINUTES):
        return None
    return moment


def start_time_for(*, launch: CampaignLaunch, now: datetime) -> str:
    moment = start_at(launch=launch, now=now)
    return moment.isoformat() if moment else ""


def end_at(*, launch: CampaignLaunch) -> datetime | None:
    if launch.end_date is None or launch.ad_account is None:
        return None
    zone = launch.ad_account.tzinfo()
    return datetime.combine(launch.end_date + timedelta(days=1), time.min, tzinfo=zone)


def runs_long_enough(*, launch: CampaignLaunch, now: datetime) -> bool:
    end = end_at(launch=launch)
    if end is None:
        return True
    return end - (start_at(launch=launch, now=now) or now) > MIN_RUN


def end_time_for(*, launch: CampaignLaunch) -> str:
    moment = end_at(launch=launch)
    return moment.isoformat() if moment else ""


def start_day(*, launch: CampaignLaunch, zone_name: str, now: datetime) -> StartDay:
    moment = start_at(launch=launch, now=now)
    if moment is not None:
        local = moment.astimezone(_zone(zone_name, fallback=moment.tzinfo or UTC))
        return StartDay(
            day=local.date(),
            hour=None if local.time() == time.min else local.time(),
            starts_early=False,
        )
    midnight = _midnight(launch=launch)
    return StartDay(
        day=None, hour=None, starts_early=midnight is not None and midnight > now
    )


def offered_days(*, launch: CampaignLaunch, now: datetime) -> tuple[date, date]:
    zone = launch.ad_account.tzinfo() if launch.ad_account else now.tzinfo
    today = now.astimezone(zone).date()
    return today, today + timedelta(days=1)


def _midnight(*, launch: CampaignLaunch) -> datetime | None:
    if launch.start_date is None or launch.ad_account is None:
        return None
    zone = launch.ad_account.tzinfo()
    return datetime.combine(launch.start_date, time.min, tzinfo=zone)


def _zone(name: str, *, fallback: tzinfo) -> tzinfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return fallback


# -- names -----------------------------------------------------------------------------


def effective_campaign_name(
    *, launch: CampaignLaunch, business: Business | None
) -> str:
    stored = (launch.campaign_name or "").strip()
    if stored:
        return stored
    if business is None:
        return ""
    return campaign_name(launch=launch, business=business)


def effective_ad_name(
    *, launch: CampaignLaunch, business: Business | None, variant: LaunchCreative
) -> str:
    stored = (variant.ad_name or "").strip()
    if stored:
        return stored
    if business is None:
        return ""
    return ad_name(launch=launch, business=business, position=variant.position)


# -- limits ----------------------------------------------------------------------------


def max_creatives() -> int:
    asked = int(getattr(settings, "ads_max_creatives", MAX_ADS_PER_CAMPAIGN))
    return max(1, min(asked, MAX_ADS_PER_CAMPAIGN))


def max_adsets_per_campaign() -> int:
    asked = int(
        getattr(settings, "ads_max_adsets_per_campaign", DEFAULT_ADSETS_PER_CAMPAIGN)
    )
    return max(1, asked)
