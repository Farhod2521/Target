"""Which kind of campaign a launch's goal is bought as, and whose choice it is."""

from dataclasses import dataclass
from typing import Any

from app.common.config import settings
from app.modules.ads import draft as draft_field
from app.modules.ads.constants import (
    CAMPAIGN_TYPE,
    CAMPAIGN_TYPE_HINTS,
    CAMPAIGN_TYPE_LABELS,
    GOAL_BY_AI,
    GOAL_READING,
    LaunchStatus,
    LaunchStep,
)
from app.modules.ads.models import CampaignLaunch
from core.targeting import campaign_type, types_for

BUILT_STATUSES = (LaunchStatus.CREATING, LaunchStatus.CREATED)


def picker_v2_on(*, user: Any) -> bool:
    """Whether this person sees the three-question picker."""
    if settings.launch_goal_picker_v2:
        return True
    email = str(getattr(user, "email", "") or "").casefold()
    wanted = {str(item).casefold() for item in settings.launch_goal_picker_v2_users}
    return bool(email) and email in wanted


def chosen_campaign_type(*, launch: CampaignLaunch) -> str:
    """The owner's choice, then the rules', as a key. ``""`` when neither."""
    owner = str(launch.answers.get(CAMPAIGN_TYPE) or "")
    return owner or draft_field.campaign_type(launch.draft or {})


def effective_campaign_type(*, launch: CampaignLaunch) -> str:
    """The key the builder will actually use - the goal's default included."""
    kind = campaign_type(
        provider=launch.provider,
        goal=str(launch.answers.get("goal") or ""),
        key=chosen_campaign_type(launch=launch),
    )
    return kind.key if kind is not None else ""


def campaign_type_source(*, launch: CampaignLaunch) -> str:
    """Who settled it: ``owner``, ``ai``, or ``""`` for a draft nobody did."""
    stored = launch.answers.get(CAMPAIGN_TYPE)
    if stored:
        return draft_field.BY_AI if stored == read_as(launch) else draft_field.BY_OWNER
    return draft_field.source(launch.draft or {}, draft_field.CAMPAIGN_TYPE)


def read_as(launch: CampaignLaunch) -> str:
    """The row the model chose from the owner's words on the first step."""
    raw = launch.answers.get(GOAL_READING)
    if not isinstance(raw, dict) or raw.get("by") != GOAL_BY_AI:
        return ""
    return str(raw.get("row") or "") if raw.get("state") == "found" else ""


def campaign_type_locked(*, launch: CampaignLaunch) -> bool:
    """Whether the kind is already fixed at the provider."""
    from app.modules.ads.selectors.launches import stranded_refs_of

    if launch.status in BUILT_STATUSES:
        return True
    left = stranded_refs_of(launch)
    return LaunchStep.CAMPAIGN in left or LaunchStep.ADSET in left


@dataclass(frozen=True, slots=True)
class CampaignTypeCard:
    label: Any
    source: str
    note: Any = ""


def campaign_type_card(*, launch: CampaignLaunch) -> CampaignTypeCard | None:
    """What the proposal says about the kind of campaign, or ``None``."""
    from app.modules.ads.selectors.advice import campaign_type_recommendation

    key = effective_campaign_type(launch=launch)
    if not key:
        return None
    source = campaign_type_source(launch=launch)
    advice = (
        campaign_type_recommendation(launch=launch)
        if source == draft_field.BY_AI and not launch.answers.get(CAMPAIGN_TYPE)
        else None
    )
    return CampaignTypeCard(
        label=CAMPAIGN_TYPE_LABELS.get(key, key),
        source=source,
        note=advice.note if advice is not None else "",
    )


@dataclass(frozen=True, slots=True)
class CampaignTypeOption:
    key: str
    label: Any
    hint: Any
    provider_label: str
    provider_goal_label: str
    recommended: bool


@dataclass(frozen=True, slots=True)
class CampaignTypeChoices:
    options: tuple[CampaignTypeOption, ...]
    chosen: str
    locked: bool
    source: str
    note: Any
    from_plan: bool = False

    @property
    def chosen_option(self) -> CampaignTypeOption | None:
        return next((o for o in self.options if o.key == self.chosen), None)


def campaign_type_choices(*, launch: CampaignLaunch) -> CampaignTypeChoices | None:
    """The tab's radios, or ``None`` for a goal with no kinds to choose from."""
    from app.modules.ads.selectors.advice import campaign_type_recommendation

    goal = str(launch.answers.get("goal") or "")
    kinds = types_for(provider=launch.provider, goal=goal)
    if not kinds:
        return None
    advice = campaign_type_recommendation(launch=launch)
    recommended = advice.value if advice is not None else ""
    return CampaignTypeChoices(
        options=tuple(
            CampaignTypeOption(
                key=row.key,
                label=CAMPAIGN_TYPE_LABELS.get(row.key, row.key),
                hint=CAMPAIGN_TYPE_HINTS.get(row.key, ""),
                provider_label=row.provider_label,
                provider_goal_label=row.provider_goal_label,
                recommended=row.key == recommended,
            )
            for row in kinds
        ),
        chosen=effective_campaign_type(launch=launch),
        locked=campaign_type_locked(launch=launch),
        source=campaign_type_source(launch=launch),
        note=advice.note if advice is not None else "",
        from_plan=picker_v2_on(user=launch.owner),
    )
