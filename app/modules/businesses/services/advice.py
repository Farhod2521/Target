"""What the office advises a kind of business.

Five things for a direction, and they hold for every narrower kind under
it: the goal to offer first and why, the second goal and when it is the
better one, and what an advert must not say. Nothing here is guessed: a
direction the office has not written about has no advice, and a goal the
direction's catalogue cannot run is refused when it is written, not when a
customer is offered it.
"""

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.presets import offered_goals
from app.modules.accounts.models import User
from app.modules.businesses.constants import AdvisedGoal
from app.modules.businesses.exceptions import BadAdvice
from app.modules.businesses.models import BusinessCategory, BusinessTypeRule

REASON_CHARS = 500
NEVER_SAY_CHARS = 1500
# ``telegram`` is run as ``traffic`` with a Telegram link.
_RUN_AS = {AdvisedGoal.TELEGRAM.value: AdvisedGoal.TRAFFIC.value}


@dataclass(frozen=True, slots=True)
class Advice:
    goal_first: str
    reason_first: str
    goal_second: str
    when_second: str
    never_say: str

    @property
    def goals(self) -> tuple[str, ...]:
        """The goals to offer, the advised one first."""
        return tuple(goal for goal in (self.goal_first, self.goal_second) if goal)


def runnable(direction: BusinessCategory) -> frozenset[str]:
    """The goals the office may advise this direction: the ones its
    catalogue offers, and ``telegram`` where ``traffic`` is one of them."""
    offered = {preset.goal for preset in offered_goals(category=direction.preset_key)}
    known = {goal.value for goal in AdvisedGoal}
    allowed = offered & known
    if AdvisedGoal.TRAFFIC.value in allowed:
        allowed.add(AdvisedGoal.TELEGRAM.value)
    return frozenset(allowed)


def _plain(words: str, *, limit: int, what: str) -> str:
    text = "\n".join(
        " ".join(line.split()) for line in str(words or "").strip().splitlines()
    ).strip()
    if len(text) > limit:
        raise BadAdvice(f"{what} {limit} belgidan oshmasin.")
    return text


def rule_of(db: Session, *, direction: BusinessCategory) -> BusinessTypeRule | None:
    return db.scalar(
        select(BusinessTypeRule).where(BusinessTypeRule.direction_id == direction.id)
    )


def advice_of(db: Session, *, direction: BusinessCategory | None) -> Advice | None:
    """The advice for a direction, or ``None`` when the office has named no
    goal for it."""
    if direction is None:
        return None
    rule = rule_of(db, direction=direction)
    if rule is None or not rule.goal_first:
        return None
    return Advice(
        goal_first=rule.goal_first,
        reason_first=rule.reason_first,
        goal_second=rule.goal_second,
        when_second=rule.when_second,
        never_say=rule.never_say,
    )


def save_rule(
    db: Session,
    *,
    direction: BusinessCategory,
    goal_first: str,
    reason_first: str,
    goal_second: str = "",
    when_second: str = "",
    never_say: str = "",
    actor: User | None = None,
) -> BusinessTypeRule:
    """Write the direction's advice over what was there; flushes."""
    first, second = str(goal_first or "").strip(), str(goal_second or "").strip()
    allowed = runnable(direction)
    for goal in (first, second):
        if goal and goal not in allowed:
            raise BadAdvice("Bu turda bunday maqsad yo'q. Ro'yxatdan tanlang.")
    if second and not first:
        raise BadAdvice("Avval birinchi maqsadni tanlang.")
    if first and first == second:
        raise BadAdvice("Ikkinchi maqsad birinchisidan boshqa bo'lsin.")
    reason = _plain(reason_first, limit=REASON_CHARS, what="Sabab")
    when = _plain(when_second, limit=REASON_CHARS, what="Izoh")
    never = _plain(never_say, limit=NEVER_SAY_CHARS, what="Cheklovlar")
    if first and not reason:
        raise BadAdvice("Birinchi maqsadning sababini yozing: mijoz shuni o'qiydi.")
    if second and not when:
        raise BadAdvice("Ikkinchi maqsad qachon yaxshiroq ekanini yozing.")
    rule = rule_of(db, direction=direction)
    if rule is None:
        rule = BusinessTypeRule(direction_id=direction.id)
        db.add(rule)
    rule.goal_first, rule.reason_first = first, reason if first else ""
    rule.goal_second, rule.when_second = second, when if second else ""
    rule.never_say = never
    rule.updated_by_id = actor.id if actor is not None else None
    db.flush()
    return rule


def run_as(goal: str) -> str:
    """The catalogue's goal an advised goal is run as."""
    return _RUN_AS.get(str(goal), str(goal))


__all__ = ["Advice", "advice_of", "rule_of", "run_as", "runnable", "save_rule"]
