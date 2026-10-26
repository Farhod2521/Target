"""Which event on the owner's own site this launch is bought against."""

from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.modules.ads import draft as draft_field
from app.modules.ads.constants import CONVERSION_EVENT, CONVERSION_EVENT_LABELS
from app.modules.ads.models import CampaignLaunch
from app.modules.ads.selectors.advice import conversion_event_recommendation
from app.modules.ads.selectors.campaign_type import campaign_type_locked
from app.modules.ads.selectors.goals import goal_objective, goal_preset
from core.targeting import EVENT_KEY, ConversionEvent, conversion_event, events_for


def offered_events(
    db: Session, *, launch: CampaignLaunch
) -> tuple[ConversionEvent, ...]:
    if not preset_event(db, launch=launch):
        return ()
    return events_for(
        provider=launch.provider, objective=goal_objective(db, launch=launch)
    )


def preset_event(db: Session, *, launch: CampaignLaunch) -> str:
    preset = goal_preset(db, launch=launch)
    if preset is None:
        return ""
    found = preset.promoted_object.get(EVENT_KEY)
    return str(found) if isinstance(found, str) else ""


def chosen_conversion_event(*, launch: CampaignLaunch) -> str:
    owner = str(launch.answers.get(CONVERSION_EVENT) or "")
    return owner or draft_field.conversion_event(launch.draft or {})


def effective_conversion_event(db: Session, *, launch: CampaignLaunch) -> str:
    """The event the builder will actually send. ``""`` when the goal has none."""
    default = preset_event(db, launch=launch)
    if not default:
        return ""
    known = conversion_event(
        provider=launch.provider, key=chosen_conversion_event(launch=launch)
    )
    return known.key if known in offered_events(db, launch=launch) else default


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
    options = tuple(
        ConversionEventOption(
            key=row.key,
            label=CONVERSION_EVENT_LABELS.get(row.key, row.key),
            provider_label=row.provider_label,
            recommended=row.key == recommended,
            arriving=row.key in arriving,
        )
        for row in offered
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
            offered=tuple(row.key for row in offered_events(db, launch=launch)),
        )
        if source == draft_field.BY_AI
        else None
    )
    return ConversionEventCard(
        label=CONVERSION_EVENT_LABELS.get(key, key),
        source=source,
        note=advice.note if advice is not None else "",
    )
