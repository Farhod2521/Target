"""The owner's answer to one of the guard's findings.

One press, one of the answers the finding offers - see
:func:`app.modules.agent.guard_copy.buttons_of`. A stop, a lower budget and
a switch back on are asked of the provider the way every change here is;
«leave» and «keep it off» are only written down. Nothing is asked twice: a
finding already answered with a change says so instead of repeating it.
"""

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.ads import actions
from app.modules.ads.constants import ManagedLevel
from app.modules.ads.models import AdSet
from app.modules.agent.exceptions import GuardAlertGone, GuardAnswerUnknown
from app.modules.agent.guard_copy import buttons_of
from app.modules.agent.models import GuardAlert
from app.modules.agent.selectors.guard import COUNTED
from core.agent.guard import BUDGET_STEP_PCT

# Answers that end the finding: the group or the advert is off, or the
# owner chose to leave it off.
CLOSING = frozenset({"pause", "pause_ad", "keep_off", "resume"})
# Answers that change something at the provider.
CHANGING = frozenset({"pause", "pause_ad", "budget_down", "resume"})


def open_guard_alert(db: Session, *, user: User, alert_id: str) -> GuardAlert:
    """One of the owner's open findings, locked. Raises when it is gone."""
    try:
        pk = uuid.UUID(str(alert_id))
    except ValueError:
        raise GuardAlertGone from None
    row = db.scalar(
        select(GuardAlert)
        .where(
            GuardAlert.owner_id == user.id,
            GuardAlert.id == pk,
            GuardAlert.closed_at.is_(None),
        )
        .with_for_update()
    )
    if row is None:
        raise GuardAlertGone
    return row


def answer_guard(
    db: Session, *, user: User, alert_id: str, answer: str, now: datetime
) -> GuardAlert:
    """Carry out one answer. Caller commits."""
    row = open_guard_alert(db, user=user, alert_id=alert_id)
    if answer not in buttons_of(row) or answer == "add_creative":
        raise GuardAnswerUnknown
    if answer in CHANGING and row.answer in CHANGING:
        raise GuardAlertGone
    if answer == "pause":
        _ask(
            db,
            user,
            actions.Pause(level=ManagedLevel.ADSET, external_id=row.adset_external_id),
        )
        # Switched back on today, the group is counted from here.
        row.baseline = _baseline(row)
    elif answer == "pause_ad":
        _ask(
            db, user, actions.Pause(level=ManagedLevel.AD, external_id=row.external_id)
        )
    elif answer == "resume":
        _ask(
            db,
            user,
            actions.Resume(level=ManagedLevel.ADSET, external_id=row.adset_external_id),
        )
    elif answer == "budget_down":
        _ask(db, user, _lower_budget(db, user=user, row=row))
    row.answer, row.answered_at = answer, now
    if answer in CLOSING:
        row.closed_at = now
    db.flush()
    return row


def _ask(db: Session, user: User, ask: object) -> None:
    actions.request(db, user=user, ask=ask)  # type: ignore[arg-type]


def _baseline(row: GuardAlert) -> dict[str, object]:
    figures = row.figures or {}
    counted = {
        "spend_minor": figures.get("group_spend_minor", figures.get("spend_minor", 0)),
        "results": figures.get("results", 0),
        "impressions": figures.get("impressions", 0),
        "link_clicks": figures.get("link_clicks", 0),
    }
    return {"day": figures.get("day", ""), **{name: counted[name] for name in COUNTED}}


def _lower_budget(db: Session, *, user: User, row: GuardAlert) -> actions.Budget:
    group = db.scalar(
        select(AdSet).where(
            AdSet.owner_id == user.id, AdSet.external_id == row.adset_external_id
        )
    )
    if group is None or not group.daily_budget_minor:
        raise GuardAnswerUnknown
    lowered = group.daily_budget_minor * (100 - BUDGET_STEP_PCT) // 100
    return actions.Budget(
        level=ManagedLevel.ADSET,
        external_id=row.adset_external_id,
        daily_budget_minor=lowered,
    )


__all__ = ["CHANGING", "CLOSING", "answer_guard", "open_guard_alert"]
