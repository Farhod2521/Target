"""What this account allows right now, as the engine reads it.

Every figure comes from where the wizard's first screen takes it
(``ads.inputs.plan``), so the chat can never offer a goal, a floor or a
channel the screen would refuse.
"""

from datetime import datetime

from sqlalchemy.orm import Session

from app.common.presets import goal_label, offered_goals
from app.modules.accounts.models import User
from app.modules.ads.constants import CHAT_CHANNEL_LABELS
from app.modules.ads.inputs.plan import plan_frame, presets_for
from app.modules.ads.models import CampaignLaunch
from app.modules.ads.selectors.campaign_type import picker_v2_on
from app.modules.ads.selectors.goals import legacy_plan_goals
from app.modules.ads.selectors.telegram import TELEGRAM_GOAL
from app.modules.billing.selectors.prices import usd_rate
from app.modules.businesses.constants import TypeState
from app.modules.businesses.models import Business
from app.modules.businesses.selectors.knowledge import Known, known
from core.launch_agent import Frame, GoalAdvice, GoalFrame

# How many known things are offered as buttons.
MAX_OFFERS = 4


def _goals(
    db: Session, *, launch: CampaignLaunch, user: User, category: str, now: datetime
) -> tuple[GoalFrame, ...]:
    presets = (
        offered_goals(provider=launch.provider, category=category)
        if picker_v2_on(user=user)
        else legacy_plan_goals(provider=launch.provider, category=category)
    )
    found: list[GoalFrame] = []
    for preset in presets:
        plan = plan_frame(db, launch=launch, user=user, goal=preset.goal, now=now)
        found.append(
            GoalFrame(
                key=preset.goal,
                label=str(goal_label(preset=preset)),
                min_daily_minor=plan.min_daily_minor,
                needs_link=plan.needs_link,
                telegram=preset.goal == TELEGRAM_GOAL,
                needs_phone=plan.needs_phone,
                opens_chat=plan.opens_chat,
                channels=tuple(
                    (str(key), str(CHAT_CHANNEL_LABELS.get(key, key)))
                    for key in plan.channels
                ),
                # The form is chosen after the pictures, on the launch's own
                # form step: its ready-made form is written from them.
                needs_form=False,
                budgets=tuple(str(sum_) for sum_ in presets_for(plan)),
            )
        )
    return tuple(found)


def _advice(view: Known, goals: tuple[GoalFrame, ...]) -> GoalAdvice | None:
    """The targetolog's advice for this kind of business, when the office
    wrote one and its first goal can be bought here. Nothing otherwise: the
    goals are then offered with no recommendation."""
    advice = view.advice
    offered = {goal.key for goal in goals}
    if advice is None or advice.goal_first not in offered:
        return None
    second = advice.goal_second if advice.goal_second in offered else ""
    return GoalAdvice(
        first=advice.goal_first,
        reason_first=advice.reason_first,
        second=second,
        when_second=advice.when_second if second else "",
    )


def _offers(view: Known) -> tuple[tuple[str, str], ...]:
    """What the business is known to sell, newest first: one press says
    what this advert is about."""
    sold = sorted(
        view.active_items, key=lambda one: str(one.get("at") or ""), reverse=True
    )
    found = []
    for item in sold[:MAX_OFFERS]:
        name = str(item.get("name") or "")
        price = str(item.get("price") or "")
        if name:
            found.append((name, f"{name} — {price}" if price else name))
    return tuple(found)


def kind_label(view: Known) -> str:
    if not view.type_label:
        return ""
    return view.type_label + (f" → {view.subtype.name}" if view.subtype else "")


def build_frame(
    db: Session,
    *,
    launch: CampaignLaunch,
    user: User,
    business: Business,
    now: datetime,
) -> Frame:
    view = known(db, business)
    goals = _goals(db, launch=launch, user=user, category=business.category, now=now)
    places = plan_frame(
        db, launch=launch, user=user, goal=goals[0].key if goals else "", now=now
    ).places
    rate = usd_rate()
    return Frame(
        goals=goals,
        currency=launch.currency,
        minor_per_unit=10**places,
        uzs_per_usd=int(rate[0]) if rate is not None else 0,
        kind_known=view.type_state != TypeState.UNSET,
        kind_label=kind_label(view),
        advice=_advice(view, goals),
        known_link=str(business.website or ""),
        known_phone=str(business.contact_phone or ""),
        offers=_offers(view),
    )


__all__ = ["build_frame", "kind_label"]
