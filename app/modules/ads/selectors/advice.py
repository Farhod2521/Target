"""The facts behind each recommendation, gathered and handed to the rules."""

from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.modules.ads import draft as draft_field
from app.modules.ads.constants import (
    ADVICE_REASONS,
    CUSTOM,
    QUESTION_TYPES,
    DraftSection,
)
from app.modules.ads.models import CampaignLaunch
from app.modules.leads.selectors.reads import FormOption
from core.advice import (
    Advice,
    FormOffer,
    audience_advice,
    buying_advice,
    campaign_type_advice,
    conversion_event_advice,
    form_advice,
    placement_advice,
)
from core.leads import form_signature
from core.targeting import REQUEST_EVENTS, types_for


@dataclass(frozen=True, slots=True)
class Recommendation:
    value: str
    note: Any


def audience_recommendation() -> Recommendation:
    return _rendered(audience_advice())


def placement_recommendation() -> Recommendation:
    return _rendered(placement_advice())


def buying_recommendation(*, is_offered: bool) -> Recommendation | None:
    return _rendered_or_none(buying_advice(is_offered=is_offered))


def form_recommendation(
    *, launch: CampaignLaunch, options: tuple[FormOption, ...]
) -> Recommendation | None:
    """Which existing form already asks this, or the advice to build one."""
    return _rendered_or_none(
        form_advice(
            asked=_asked_questions(launch),
            offers=tuple(
                FormOffer(
                    external_id=option.external_id,
                    signature=option.signature,
                    leads_count=option.leads_count,
                )
                for option in options
            ),
        )
    )


def campaign_type_recommendation(*, launch: CampaignLaunch) -> Recommendation | None:
    goal = str(launch.answers.get("goal") or "")
    kinds = tuple(row.key for row in types_for(provider=launch.provider, goal=goal))
    return _rendered_or_none(campaign_type_advice(goal=goal, kinds=kinds))


@dataclass(frozen=True, slots=True)
class EventRecommendation:
    value: str
    note: Any
    arriving: tuple[str, ...]


def conversion_event_recommendation(
    db: Session, *, launch: CampaignLaunch, offered: tuple[str, ...]
) -> EventRecommendation | None:
    """Which event on the owner's own site this campaign should be bought on."""
    from app.modules.ads.selectors.pixel import chosen_pixel
    from app.modules.integrations.selectors.watch import fired_events

    if not offered:
        return None
    arriving = fired_events(owner=launch.owner, pixel=chosen_pixel(db, launch=launch))
    advice = conversion_event_advice(
        offered=offered, fired=arriving, requests=REQUEST_EVENTS
    )
    if advice is None:
        return None
    return EventRecommendation(
        value=advice.value,
        note=ADVICE_REASONS.get(advice.reason, ""),
        arriving=arriving,
    )


def _asked_questions(launch: CampaignLaunch) -> tuple[str, ...]:
    chosen = draft_field.chosen(launch.draft or {}, DraftSection.FORM) or []
    return form_signature(
        {
            "type": QUESTION_TYPES.get(str(item.get("kind", "")), CUSTOM),
            "label": str(item.get("label", "")),
        }
        for item in chosen
        if isinstance(item, dict)
    )


def _rendered(advice: Advice) -> Recommendation:
    return Recommendation(
        value=advice.value, note=ADVICE_REASONS.get(advice.reason, "")
    )


def _rendered_or_none(advice: Advice | None) -> Recommendation | None:
    return None if advice is None else _rendered(advice)
