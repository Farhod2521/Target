"""The answers about how the advert is counted, how often it shows, and its price."""

from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from app.common.money import provider_money, to_major
from app.modules.ads.constants import (
    ATTRIBUTION,
    ATTRIBUTION_LABELS,
    COST_CAP_LABEL,
    FREQUENCY_CAP,
)
from app.modules.ads.models import CampaignLaunch
from app.modules.ads.selectors.campaign_type import campaign_type_locked
from app.modules.ads.selectors.goals import goal_optimization, goal_preset
from core.targeting import accepts_cap, takes_attribution, windows_for
from core.targeting.budget import FREQUENCY_GOALS

MAX_CAP_DAYS = 90


def goal_is_seen_rather_than_acted_on(db: Session, *, launch: CampaignLaunch) -> bool:
    return goal_optimization(db, launch=launch) in FREQUENCY_GOALS


def goal_counts_on_the_site(db: Session, *, launch: CampaignLaunch) -> bool:
    return takes_attribution(goal_optimization(db, launch=launch))


def goal_builds_a_form(db: Session, *, launch: CampaignLaunch) -> bool:
    preset = goal_preset(db, launch=launch)
    return preset is not None and preset.needs_lead_form


@dataclass(frozen=True, slots=True)
class WindowOption:
    key: str
    label: Any
    provider_label: str


@dataclass(frozen=True, slots=True)
class DeliveryChoices:
    windows: tuple[WindowOption, ...]
    chosen_window: str
    cap_times: int | None
    cap_days: int | None
    offers_window: bool
    offers_cap: bool
    locked: bool


def delivery_choices(db: Session, *, launch: CampaignLaunch) -> DeliveryChoices:
    times, days = frequency_cap_of(launch.answers.get(FREQUENCY_CAP))
    return DeliveryChoices(
        windows=tuple(
            WindowOption(
                key=row.key,
                label=ATTRIBUTION_LABELS.get(row.key, row.key),
                provider_label=row.provider_label,
            )
            for row in windows_for(provider=launch.provider)
        ),
        chosen_window=str(launch.answers.get(ATTRIBUTION) or ""),
        offers_window=goal_counts_on_the_site(db, launch=launch),
        cap_times=times,
        cap_days=days,
        offers_cap=goal_is_seen_rather_than_acted_on(db, launch=launch),
        locked=campaign_type_locked(launch=launch),
    )


def frequency_cap_of(value: object) -> tuple[int | None, int | None]:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return None, None
    try:
        return int(value[0]), int(value[1])
    except (TypeError, ValueError):
        return None, None


@dataclass(frozen=True, slots=True)
class CostCapChoice:
    currency: str
    amount: Any
    label: Any
    locked: bool


def cost_cap_choice(db: Session, *, launch: CampaignLaunch) -> CostCapChoice | None:
    """The price-per-result box, or ``None`` for a kind whose result takes none."""
    if not accepts_cap(goal_optimization(db, launch=launch)):
        return None
    places = provider_money(provider=launch.provider).decimal_places(launch.currency)
    return CostCapChoice(
        currency=launch.currency,
        amount=to_major(amount_minor=launch.max_result_cost_minor, places=places),
        label=COST_CAP_LABEL,
        locked=campaign_type_locked(launch=launch),
    )
