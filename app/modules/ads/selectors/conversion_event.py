"""Which event on the owner's own site this launch is bought against."""

from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.modules.ads import draft as draft_field
from app.modules.ads.constants import (
    CONVERSION_EVENT,
    CONVERSION_EVENT_LABELS,
    CUSTOM_CONVERSION,
    EVENT_FEW,
    EVENT_NOT_ARRIVING,
    FEW_EVENTS,
)
from app.modules.ads.models import CampaignLaunch
from app.modules.ads.selectors.advice import conversion_event_recommendation
from app.modules.ads.selectors.campaign_type import campaign_type_locked
from app.modules.ads.selectors.goals import goal_preset
from app.modules.ads.selectors.pixel import chosen_pixel, usable_pixels
from core.targeting import EVENT_KEY, ConversionEvent, conversion_events
from core.targeting.conversion_events import event_for_snippet


def offered_events(
    db: Session, *, launch: CampaignLaunch
) -> tuple[ConversionEvent, ...]:
    """TZ 3: every event the provider counts - the objective follows the pick."""
    if not preset_event(db, launch=launch):
        return ()
    return conversion_events(provider=launch.provider)


@dataclass(frozen=True, slots=True)
class CustomConversion:
    key: str
    external_id: str
    name: str
    event: str
    count: int | None


def offered_conversions(
    db: Session, *, launch: CampaignLaunch, pixel_id: str = ""
) -> tuple[CustomConversion, ...]:
    """The chosen pixel's custom conversions, keyed ``cc:<id>`` beside the events.

    Only those counted as one of the provider's events: the ad set is bought
    on that event with the conversion beside it, and a type this product does
    not know would be bought as the preset's own event instead.
    """
    if not preset_event(db, launch=launch):
        return ()
    known = {row.key for row in conversion_events(provider=launch.provider)}
    pixel = chosen_pixel(db, launch=launch)
    if pixel_id:
        # The pixel picked in the same save as the event (TZ 3).
        pixel = next(
            (
                row
                for row in usable_pixels(db, launch=launch)
                if row.external_id == pixel_id
            ),
            pixel,
        )
    rows = pixel.conversions if pixel and isinstance(pixel.conversions, list) else []
    return tuple(
        CustomConversion(
            key=f"{CUSTOM_CONVERSION}{row['id']}",
            external_id=str(row["id"]),
            name=str(row.get("name") or row["id"]),
            event=str(row.get("event") or "OTHER"),
            count=_count(row.get("count")),
        )
        for row in rows
        if isinstance(row, dict)
        and row.get("id")
        and str(row.get("event") or "") in known
    )


def offered_keys(
    db: Session, *, launch: CampaignLaunch, pixel_id: str = ""
) -> tuple[str, ...]:
    return tuple(row.key for row in offered_events(db, launch=launch)) + tuple(
        row.key for row in offered_conversions(db, launch=launch, pixel_id=pixel_id)
    )


def chosen_conversion(
    db: Session, *, launch: CampaignLaunch
) -> CustomConversion | None:
    """The custom conversion this launch is bought on, if one was chosen."""
    key = effective_conversion_event(db, launch=launch)
    if not key.startswith(CUSTOM_CONVERSION):
        return None
    return next(
        (row for row in offered_conversions(db, launch=launch) if row.key == key),
        None,
    )


def event_counts(db: Session, *, launch: CampaignLaunch) -> dict[str, int] | None:
    """Seven-day count per event key; ``None`` before the pixel was ever read."""
    pixel = chosen_pixel(db, launch=launch)
    if pixel is None or pixel.events_synced_at is None:
        return None
    counts: dict[str, int] = {}
    for row in pixel.recent_events if isinstance(pixel.recent_events, list) else []:
        if not isinstance(row, dict):
            continue
        found = event_for_snippet(
            provider=pixel.provider, name=str(row.get("event", ""))
        )
        if found is not None:
            counts[found.key] = counts.get(found.key, 0) + (
                _count(row.get("count")) or 0
            )
    return counts


def event_warning(count: int | None) -> Any:
    """TZ 3: none in seven days, or fewer than ten. The pick is never refused."""
    if count is None:
        return ""
    if count == 0:
        return EVENT_NOT_ARRIVING
    if count < FEW_EVENTS:
        return EVENT_FEW
    return ""


def _count(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(str(value))
    except ValueError:
        return None


def preset_event(db: Session, *, launch: CampaignLaunch) -> str:
    preset = goal_preset(db, launch=launch)
    if preset is None:
        return ""
    found = preset.promoted_object.get(EVENT_KEY)
    return str(found) if isinstance(found, str) else ""


def chosen_conversion_event(*, launch: CampaignLaunch) -> str:
    owner = str(launch.answers.get(CONVERSION_EVENT) or "")
    return owner or draft_field.conversion_event(launch.draft or {})


def event_label(db: Session, *, launch: CampaignLaunch, key: str) -> str:
    """What a chosen event is called: a custom conversion by its own name."""
    if not key.startswith(CUSTOM_CONVERSION):
        return key
    found = next(
        (row for row in offered_conversions(db, launch=launch) if row.key == key), None
    )
    return found.name if found is not None else key


def effective_conversion_event(db: Session, *, launch: CampaignLaunch) -> str:
    """The event the builder will actually send. ``""`` when the goal has none."""
    default = preset_event(db, launch=launch)
    if not default:
        return ""
    chosen = chosen_conversion_event(launch=launch)
    return chosen if chosen in offered_keys(db, launch=launch) else default


def conversion_event_source(*, launch: CampaignLaunch) -> str:
    if launch.answers.get(CONVERSION_EVENT):
        return draft_field.BY_OWNER
    return draft_field.source(launch.draft or {}, draft_field.CONVERSION_EVENT)


@dataclass(frozen=True, slots=True)
class ConversionEventOption:
    key: str
    label: Any
    provider_label: str
    recommended: bool
    arriving: bool
    # TZ 3: seven-day count (None before the pixel was read) and its warning.
    count: int | None = None
    warning: Any = ""
    group: str = "event"


@dataclass(frozen=True, slots=True)
class ConversionEventChoices:
    arriving_options: tuple[ConversionEventOption, ...]
    other_options: tuple[ConversionEventOption, ...]
    chosen: str
    locked: bool
    source: str
    note: Any
    seen_any: bool


def conversion_event_choices(
    db: Session, *, launch: CampaignLaunch
) -> ConversionEventChoices | None:
    offered = offered_events(db, launch=launch)
    if not offered:
        return None
    advice = conversion_event_recommendation(
        db, launch=launch, offered=tuple(row.key for row in offered)
    )
    recommended = advice.value if advice is not None else ""
    arriving = set(advice.arriving if advice is not None else ())
    counts = event_counts(db, launch=launch)
    options = tuple(
        ConversionEventOption(
            key=row.key,
            label=CONVERSION_EVENT_LABELS.get(row.key, row.key),
            provider_label=row.provider_label,
            recommended=row.key == recommended,
            arriving=row.key in arriving,
            count=None if counts is None else counts.get(row.key, 0),
            warning=event_warning(None if counts is None else counts.get(row.key, 0)),
        )
        for row in offered
    ) + tuple(
        ConversionEventOption(
            key=row.key,
            label=row.name,
            provider_label="Custom conversion",
            recommended=False,
            arriving=bool(row.count),
            count=row.count,
            warning=event_warning(row.count),
            group="custom",
        )
        for row in offered_conversions(db, launch=launch)
    )
    return ConversionEventChoices(
        arriving_options=tuple(row for row in options if row.arriving),
        other_options=tuple(row for row in options if not row.arriving),
        chosen=effective_conversion_event(db, launch=launch),
        locked=campaign_type_locked(launch=launch),
        source=conversion_event_source(launch=launch),
        note=advice.note if advice is not None else "",
        seen_any=bool(arriving),
    )


@dataclass(frozen=True, slots=True)
class ConversionEventCard:
    label: Any
    source: str
    note: Any = ""


def conversion_event_card(
    db: Session, *, launch: CampaignLaunch
) -> ConversionEventCard | None:
    key = effective_conversion_event(db, launch=launch)
    if not key:
        return None
    source = conversion_event_source(launch=launch)
    advice = (
        conversion_event_recommendation(
            db,
            launch=launch,
            offered=offered_keys(db, launch=launch),
        )
        if source == draft_field.BY_AI
        else None
    )
    custom = chosen_conversion(db, launch=launch)
    return ConversionEventCard(
        label=custom.name if custom else CONVERSION_EVENT_LABELS.get(key, key),
        source=source,
        note=advice.note if advice is not None else "",
    )
