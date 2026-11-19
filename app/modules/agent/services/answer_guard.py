"""The owner's answer to one of the guard's findings.

One press, one of the answers the finding offers - see
:func:`app.modules.agent.guard_copy.buttons_of`. A stop, a lower budget and
a switch back on are asked of the provider the way every change here is;
«leave» and «keep it off» are only written down. Nothing is asked twice: a
finding already answered with a change says so instead of repeating it -
unless the provider refused it, when the buttons are back.

**Only on its own pair.** A finding is about a group of one page and ad
account pair the owner has; a group no pair holds any more is not changed
from here, whichever pair the cabinet has open.

**A late answer is checked first.** A stop, a lower budget or an advert's
stop given more than half an hour after the figures the finding was written
from is not carried out on them: today's figures are read again (see
:mod:`app.modules.agent.services.recheck_guard`). Still true, it is carried
out; over, the owner is asked whether it is still wanted - «confirm» does
it, «cancel» leaves the group as it is.

**A stop ends the finding when it lands.** The row stays open while the
change is on its way, so a refusal brings the buttons back on the same row.
"""

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.db import on_commit
from app.modules.accounts.models import User
from app.modules.ads import actions
from app.modules.ads.constants import ManagedLevel
from app.modules.ads.models import AdSet
from app.modules.agent.exceptions import (
    GuardAlertGone,
    GuardAnswerUnknown,
    GuardChecking,
    GuardPairGone,
)
from app.modules.agent.guard_copy import buttons_of
from app.modules.agent.models import GuardAlert
from app.modules.agent.selectors.guard import COUNTED
from app.modules.audit.models import ActionLog
from core.agent.guard import BUDGET_STEP_PCT

# Answers that end the finding: the group or the advert is off, or the
# owner chose to leave it off. A change ends it once it lands.
CLOSING = frozenset({"pause", "pause_ad", "keep_off", "resume"})
# Answers that change something at the provider.
CHANGING = frozenset({"pause", "pause_ad", "budget_down", "resume"})
# Changes made because of what the figures said: checked again when late.
CHECKED = frozenset({"pause", "pause_ad", "budget_down"})
# The two answers to «it works well now - still do it?».
CONFIRM = "confirm"
CANCEL = "cancel"
LEAVE = "leave"
# How old the figures may be before a change made on them is checked again.
RECHECK_AFTER = timedelta(minutes=30)
# Pending states.
CHECKING_STATE = "checking"
CONFIRM_STATE = "confirm"
APPLIED = "applied"
FAILED = "failed"

State = Literal["asked", "saved", "checking", "cancelled"]


@dataclass(frozen=True, slots=True)
class Answered:
    row: GuardAlert
    answer: str
    state: State


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


def figures_at(row: GuardAlert) -> datetime:
    """When the figures the finding says were read; a row written before
    that was kept is as old as the row."""
    said = (row.figures or {}).get("at")
    if said:
        try:
            return datetime.fromisoformat(str(said))
        except ValueError:
            pass
    return row.created_at


def answer_guard(
    db: Session,
    *,
    user: User,
    alert_id: str,
    answer: str,
    now: datetime,
    confirmed: bool = False,
) -> Answered:
    """Carry out one answer, or start the second look it waits for. Caller commits."""
    row = open_guard_alert(db, user=user, alert_id=alert_id)
    if row.pending_state == CHECKING_STATE:
        raise GuardChecking
    if answer in (CONFIRM, CANCEL):
        return _settle_question(db, user=user, row=row, answer=answer, now=now)
    if answer not in buttons_of(row) or answer == "add_creative":
        raise GuardAnswerUnknown
    if answer in CHANGING and row.answer in CHANGING and row.result != FAILED:
        raise GuardAlertGone
    check_pair(db, user=user, row=row)
    if answer in CHECKED and not confirmed and now - figures_at(row) > RECHECK_AFTER:
        return _check_first(db, row=row, answer=answer, now=now)
    return carry_out(db, user=user, row=row, answer=answer, now=now)


def _settle_question(
    db: Session, *, user: User, row: GuardAlert, answer: str, now: datetime
) -> Answered:
    if row.pending_state != CONFIRM_STATE or not row.pending_answer:
        raise GuardAlertGone
    wanted = row.pending_answer
    if answer == CANCEL:
        _clear_pending(row)
        row.answer, row.answered_at = LEAVE, now
        row.answer_log_id = None
        row.result, row.result_text = "", ""
        db.flush()
        return Answered(row=row, answer=CANCEL, state="cancelled")
    check_pair(db, user=user, row=row)
    asked_at = row.pending_at or now
    if now - asked_at > RECHECK_AFTER:
        # The question itself is old now: what it showed is old too.
        return _check_first(db, row=row, answer=wanted, now=now)
    return carry_out(db, user=user, row=row, answer=wanted, now=now)


def _check_first(
    db: Session, *, row: GuardAlert, answer: str, now: datetime
) -> Answered:
    from app.modules.agent.tasks import recheck_guard_task

    row.pending_answer = answer
    row.pending_state = CHECKING_STATE
    row.pending_at = now
    row.now_figures = {}
    db.flush()
    alert_id = str(row.id)
    on_commit(db, lambda: recheck_guard_task.delay(alert_id))
    return Answered(row=row, answer=answer, state="checking")


def carry_out(
    db: Session, *, user: User, row: GuardAlert, answer: str, now: datetime
) -> Answered:
    """Ask the provider for the change, or write the answer down."""
    log = None
    if answer == "pause":
        log = _ask(
            db,
            user,
            actions.Pause(level=ManagedLevel.ADSET, external_id=row.adset_external_id),
        )
        # Switched back on today, the group is counted from here.
        row.baseline = _baseline(row)
    elif answer == "pause_ad":
        log = _ask(
            db, user, actions.Pause(level=ManagedLevel.AD, external_id=row.external_id)
        )
    elif answer == "resume":
        log = _ask(
            db,
            user,
            actions.Resume(level=ManagedLevel.ADSET, external_id=row.adset_external_id),
        )
    elif answer == "budget_down":
        ask, old = _lower_budget(db, user=user, row=row)
        log = _ask(db, user, ask)
        row.figures = {
            **(row.figures or {}),
            "budget_old_minor": old,
            "budget_new_minor": ask.daily_budget_minor,
        }
    _clear_pending(row)
    row.answer, row.answered_at = answer, now
    # The newest answer is the one the row speaks of: an earlier refusal is over.
    row.answer_log_id = log.id if log is not None else None
    row.result, row.result_text = "", ""
    if log is None and answer in CLOSING:
        # «Keep it off»: nothing to wait for.
        row.closed_at = now
    db.flush()
    return Answered(
        row=row, answer=answer, state="asked" if log is not None else "saved"
    )


def check_pair(db: Session, *, user: User, row: GuardAlert) -> None:
    """The group must still sit in one of the owner's page and account pairs,
    under the account the finding was written for."""
    from app.modules.ads.selectors.pages import page_scope

    scope = page_scope(db, owner=user)
    group = row.adset_external_id
    account = row.ad_account
    if (
        account is None
        or not account.is_active
        or not scope.allows_adset(group)
        or scope.account_of.get(group, account.external_id) != account.external_id
    ):
        raise GuardPairGone


def _clear_pending(row: GuardAlert) -> None:
    row.pending_answer, row.pending_state, row.pending_at = "", "", None


def _ask(db: Session, user: User, ask: object) -> ActionLog:
    return actions.request(db, user=user, ask=ask)  # type: ignore[arg-type]


def _baseline(row: GuardAlert) -> dict[str, object]:
    figures = row.figures or {}
    counted = {
        "spend_minor": figures.get("group_spend_minor", figures.get("spend_minor", 0)),
        "results": figures.get("results", 0),
        "impressions": figures.get("impressions", 0),
        "link_clicks": figures.get("link_clicks", 0),
    }
    return {"day": figures.get("day", ""), **{name: counted[name] for name in COUNTED}}


def _lower_budget(
    db: Session, *, user: User, row: GuardAlert
) -> tuple[actions.Budget, int]:
    group = db.scalar(
        select(AdSet).where(
            AdSet.owner_id == user.id, AdSet.external_id == row.adset_external_id
        )
    )
    if group is None or not group.daily_budget_minor:
        raise GuardAnswerUnknown
    lowered = group.daily_budget_minor * (100 - BUDGET_STEP_PCT) // 100
    return (
        actions.Budget(
            level=ManagedLevel.ADSET,
            external_id=row.adset_external_id,
            daily_budget_minor=lowered,
        ),
        int(group.daily_budget_minor),
    )


__all__ = [
    "APPLIED",
    "CANCEL",
    "CHANGING",
    "CHECKED",
    "CHECKING_STATE",
    "CLOSING",
    "CONFIRM",
    "CONFIRM_STATE",
    "FAILED",
    "RECHECK_AFTER",
    "Answered",
    "answer_guard",
    "carry_out",
    "check_pair",
    "figures_at",
    "open_guard_alert",
]
