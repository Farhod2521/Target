from collections.abc import Mapping
from datetime import date, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.common.money import format_minor
from app.modules.accounts.models import User
from app.modules.metrics.constants import EVERY_ACCOUNT, MetricLevel
from app.modules.metrics.models import MetricsDaily
from app.modules.metrics.selectors.campaigns import campaign_goal_of
from app.modules.metrics.selectors.creatives import CreativeSums, countable
from app.modules.metrics.selectors.facts import cabinet_where
from app.modules.metrics.selectors.results import (
    UNCOUNTED_LABEL,
    uncounted_note,
    words_for,
)
from core.metrics import Outcome
from core.metrics.outcomes import outcome_for

CREATIVE_WINDOW_DAYS: int = 90
NO_RESULT_NOTE = "Bu kampaniyada sanaladigan natija ko'rinmadi — reklamalarni narx bo'yicha taqqoslab bo'lmaydi."


def window(db: Session, *, owner: User, campaign: Any) -> tuple[date, date] | None:
    m = MetricsDaily
    first, last = db.execute(
        select(func.min(m.date), func.max(m.date)).where(
            *cabinet_where(
                db, owner=owner, level=MetricLevel.AD, account=EVERY_ACCOUNT
            ),
            m.provider == campaign.provider,
            m.campaign_external_id == campaign.external_id,
        )
    ).one()
    if first is None or last is None:
        return None
    return max(first, last - timedelta(days=CREATIVE_WINDOW_DAYS - 1)), last


def goal_of(
    db: Session, *, owner: User, campaign: Any
) -> tuple[str, Mapping[str, Any] | None]:
    return campaign_goal_of(db, owner=owner, campaign=campaign)


def kind_of(*, goal: str, promoted: Mapping[str, Any] | None = None) -> Outcome:
    return outcome_for(goal, promoted)


def countable_in(row: CreativeSums, *, kind: Outcome) -> int:
    return countable(row, kind=kind)


def cost_label(kind: Outcome) -> Any:
    return words_for(kind).cost_label or UNCOUNTED_LABEL


def average_of(amount: int | None, currency: str, kind: Outcome) -> str:
    if not words_for(kind).field:
        return ""
    return format_minor(amount_minor=amount, currency=currency)


def note_for(*, kind: Outcome, goal: str) -> Any:
    if words_for(kind).field:
        return ""
    goal_note = uncounted_note(goal)
    return f"{NO_RESULT_NOTE} {goal_note}".strip() if goal_note else NO_RESULT_NOTE


__all__ = [
    "CREATIVE_WINDOW_DAYS",
    "NO_RESULT_NOTE",
    "average_of",
    "cost_label",
    "countable_in",
    "goal_of",
    "kind_of",
    "note_for",
    "window",
]
