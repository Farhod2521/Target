"""The address tags and the button word of one launch, and whose answers they are."""

from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.modules.ads import draft as draft_field
from app.modules.ads.constants import BUTTON_LABELS, CALL_TO_ACTION, URL_TAGS
from app.modules.ads.models import CampaignLaunch
from app.modules.ads.selectors.campaign_type import campaign_type_locked
from app.modules.ads.selectors.goals import goal_preset
from core.targeting import (
    DEFAULT_TAGS,
    AdButton,
    button,
    buttons_for,
    clean_tags,
    tags_are_usable,
)
from core.targeting.destinations import needs_link


def goal_sends_to_a_site(db: Session, *, launch: CampaignLaunch) -> bool:
    preset = goal_preset(db, launch=launch)
    return preset is not None and needs_link(preset.sends_to)


def chosen_url_tags(*, launch: CampaignLaunch) -> str:
    if URL_TAGS in launch.answers:
        return str(launch.answers.get(URL_TAGS) or "")
    return draft_field.url_tags(launch.draft or {})


def effective_url_tags(db: Session, *, launch: CampaignLaunch) -> str:
    if not goal_sends_to_a_site(db, launch=launch):
        return ""
    given = chosen_url_tags(launch=launch)
    return clean_tags(given) if tags_are_usable(given) else ""


def url_tags_source(*, launch: CampaignLaunch) -> str:
    if URL_TAGS in launch.answers:
        return draft_field.BY_OWNER
    return draft_field.source(launch.draft or {}, draft_field.URL_TAGS)


@dataclass(frozen=True, slots=True)
class UrlTagsChoice:
    tags: str
    suggested: str
    source: str
    locked: bool


def url_tags_choice(db: Session, *, launch: CampaignLaunch) -> UrlTagsChoice | None:
    if not goal_sends_to_a_site(db, launch=launch):
        return None
    return UrlTagsChoice(
        tags=effective_url_tags(db, launch=launch),
        suggested=DEFAULT_TAGS,
        source=url_tags_source(launch=launch),
        locked=campaign_type_locked(launch=launch),
    )


# -- the button ------------------------------------------------------------------------


def offered_buttons(db: Session, *, launch: CampaignLaunch) -> tuple[AdButton, ...]:
    preset = goal_preset(db, launch=launch)
    if preset is None:
        return ()
    return buttons_for(provider=launch.provider, sends_to=preset.sends_to)


def preset_button(db: Session, *, launch: CampaignLaunch) -> str:
    preset = goal_preset(db, launch=launch)
    return preset.call_to_action if preset is not None else ""


def chosen_button(*, launch: CampaignLaunch) -> str:
    return str(launch.answers.get(CALL_TO_ACTION) or "")


def effective_button(db: Session, *, launch: CampaignLaunch) -> str:
    preset = goal_preset(db, launch=launch)
    if preset is None:
        return ""
    chosen = button(
        provider=launch.provider,
        sends_to=preset.sends_to,
        key=chosen_button(launch=launch),
    )
    return chosen.key if chosen is not None else preset.call_to_action


@dataclass(frozen=True, slots=True)
class ButtonOption:
    key: str
    label: Any
    provider_label: str


@dataclass(frozen=True, slots=True)
class ButtonChoices:
    options: tuple[ButtonOption, ...]
    chosen: str
    locked: bool
    by_owner: bool


def button_choices(db: Session, *, launch: CampaignLaunch) -> ButtonChoices | None:
    offered = offered_buttons(db, launch=launch)
    if not offered:
        return None
    return ButtonChoices(
        options=tuple(
            ButtonOption(
                key=row.key,
                label=BUTTON_LABELS.get(row.key, row.key),
                provider_label=row.provider_label,
            )
            for row in offered
        ),
        chosen=effective_button(db, launch=launch),
        locked=campaign_type_locked(launch=launch),
        by_owner=bool(chosen_button(launch=launch)),
    )
