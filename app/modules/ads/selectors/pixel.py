"""Which tag on the owner's own site this launch reports through."""

from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import Select, select
from sqlalchemy.orm import Session

from app.modules.ads.constants import PIXEL_ID
from app.modules.ads.models import CampaignLaunch
from app.modules.ads.selectors.goals import goal_preset
from app.modules.integrations.models import PixelAccount
from core.targeting import EVENT_KEY, REQUEST_EVENTS, ConversionSource
from core.targeting.conversion_events import event_for_snippet


def _usable(launch: CampaignLaunch) -> Select[tuple[PixelAccount]]:
    return select(PixelAccount).where(
        PixelAccount.owner_id == launch.owner_id,
        PixelAccount.provider == launch.provider,
        PixelAccount.ad_account_id == launch.ad_account_id,
        PixelAccount.is_unavailable.is_(False),
    )


def usable_pixels(db: Session, *, launch: CampaignLaunch) -> tuple[PixelAccount, ...]:
    return tuple(
        db.scalars(
            _usable(launch).order_by(PixelAccount.is_active.desc(), PixelAccount.name)
        )
    )


def chosen_pixel(db: Session, *, launch: CampaignLaunch) -> PixelAccount | None:
    """The tag this launch will name, or ``None`` when there is none to name.

    The owner's pick on this launch; else the pixel the website sends the
    goal's results through most (a lead for a lead goal); else the pixel
    chosen in the cabinet; else the one that sent the most events.

    The cabinet's pick is not first: it is also where CRM verdicts go, and a
    pixel made for those may be on no website at all.
    """
    named = str(launch.answers.get(PIXEL_ID) or "")
    if named:
        found = db.scalar(_usable(launch).where(PixelAccount.external_id == named))
        if found is not None:
            return found
    usable = usable_pixels(db, launch=launch)
    if not usable:
        return None
    wanted = wanted_events(db, launch=launch)
    best = max(usable, key=lambda row: site_results(row, wanted))
    if site_results(best, wanted):
        return best
    if usable[0].is_active:
        return usable[0]
    return max(usable, key=events_total)


def wanted_events(db: Session, *, launch: CampaignLaunch) -> frozenset[str]:
    """The event keys that count as this goal's result on the website."""
    preset = goal_preset(db, launch=launch)
    found = preset.promoted_object.get(EVENT_KEY) if preset is not None else None
    if not isinstance(found, str) or not found:
        return REQUEST_EVENTS
    return REQUEST_EVENTS if found in REQUEST_EVENTS else frozenset({found})


def site_results(pixel: PixelAccount, wanted: frozenset[str]) -> int:
    """How many of the wanted events came from the website's own tag this week.

    Figures read before the tag and the server were told apart have no
    ``web``; their ``count`` stands in for it.
    """
    rows = pixel.recent_events if isinstance(pixel.recent_events, list) else []
    total = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        found = event_for_snippet(
            provider=pixel.provider, name=str(row.get("event", ""))
        )
        if found is None or found.key not in wanted:
            continue
        value = row.get("web") if "web" in row else row.get("count")
        try:
            total += int(str(value or 0))
        except ValueError:
            continue
    return total


def events_total(pixel: PixelAccount) -> int:
    """Every event the pixel sent in the last seven days, as last synced."""
    rows = pixel.recent_events if isinstance(pixel.recent_events, list) else []
    total = 0
    for row in rows:
        if isinstance(row, dict):
            try:
                total += int(str(row.get("count") or 0))
            except ValueError:
                continue
    return total


def launch_conversion_source(
    db: Session, *, launch: CampaignLaunch
) -> ConversionSource | None:
    pixel = chosen_pixel(db, launch=launch)
    if pixel is None:
        return None
    return ConversionSource(external_id=pixel.external_id, name=pixel.name)


@dataclass(frozen=True, slots=True)
class PixelOption:
    external_id: str
    name: str
    is_chosen: bool
    last_fired_at: datetime | None
    events_seen: int
    # The goal's results from the website's tag this week; None before any read.
    site_results: int | None = None


def pixel_choices(db: Session, *, launch: CampaignLaunch) -> tuple[PixelOption, ...]:
    """The tab's pixel list, or nothing when there is nothing to choose."""
    found = usable_pixels(db, launch=launch)
    if len(found) < 2:
        return ()
    chosen = chosen_pixel(db, launch=launch)
    chosen_id = chosen.external_id if chosen is not None else ""
    wanted = wanted_events(db, launch=launch)
    return tuple(
        PixelOption(
            external_id=row.external_id,
            name=row.name or row.external_id,
            is_chosen=row.external_id == chosen_id,
            last_fired_at=row.last_fired_at,
            events_seen=events_total(row),
            site_results=site_results(row, wanted)
            if row.events_synced_at is not None
            else None,
        )
        for row in found
    )


@dataclass(frozen=True, slots=True)
class PixelSiteCheck:
    """Whether the launch's pixel is seen on the ad's website, said before launch.

    ``state``: ``never_fired`` (it never fired anywhere), ``not_on_site``
    (it fired this week, not on the ad's host), ``no_results`` (no result
    came through it from the site this week), or ``ok``.
    """

    state: str
    pixel: str
    host: str
    hosts: tuple[str, ...]


def _bare(host: str) -> str:
    host = host.strip().lower().rstrip(".")
    return host[4:] if host.startswith("www.") else host


def _same_site(one: str, other: str) -> bool:
    a, b = _bare(one), _bare(other)
    return bool(a and b) and (a == b or a.endswith(f".{b}") or b.endswith(f".{a}"))


def pixel_site_check(
    db: Session, *, launch: CampaignLaunch, link_url: str
) -> PixelSiteCheck | None:
    """Only warns: the owner may know better (a site behind another domain)."""
    from urllib.parse import urlsplit

    pixel = chosen_pixel(db, launch=launch)
    if pixel is None:
        return None
    typed = link_url.strip()
    if typed and "://" not in typed:
        typed = f"https://{typed}"
    host = _bare(urlsplit(typed).hostname or "") if typed else ""
    hosts = tuple(
        str(row.get("host") or "")
        for row in (pixel.hosts if isinstance(pixel.hosts, list) else [])
        if isinstance(row, dict) and row.get("host")
    )
    name = pixel.name or pixel.external_id
    if pixel.last_fired_at is None:
        return PixelSiteCheck("never_fired", name, host, hosts)
    if host and hosts and not any(_same_site(host, seen) for seen in hosts):
        return PixelSiteCheck("not_on_site", name, host, hosts)
    if pixel.events_synced_at is not None and not site_results(
        pixel, wanted_events(db, launch=launch)
    ):
        return PixelSiteCheck("no_results", name, host, hosts)
    return PixelSiteCheck("ok", name, host, hosts)
