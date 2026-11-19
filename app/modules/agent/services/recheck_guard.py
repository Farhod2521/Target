"""The second look before a late answer is carried out.

An answer given on figures over half an hour old waits here (see
:mod:`app.modules.agent.services.answer_guard`). Today's figures are read
again - from the database when the half-hourly sync read them within the
hour, from Meta now when it did not - and the group is judged by the same
rules the guard writes its findings by (:func:`core.agent.guard.judge`):

- the same finding still there: the change is carried out;
- the group no longer running: nothing is changed, and the row ends;
- the finding gone: the owner is asked whether the change is still wanted,
  with today's figures beside the question;
- the figures could not be read: the owner is asked the same, told so.

Nothing here guesses: every figure the question shows is one stored by the
sync this look ran or found fresh.
"""

import logging
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.common.exceptions import DomainError
from app.modules.agent.models import GuardAlert
from app.modules.agent.selectors.guard import Guarded, fresh, guarded_groups
from app.modules.agent.services.answer_guard import (
    CHECKING_STATE,
    CONFIRM_STATE,
    carry_out,
    check_pair,
)
from app.modules.integrations.models import AdAccount
from core.agent.guard import judge

logger = logging.getLogger(__name__)

Outcome = str  # "asked" | "confirm" | "gone" | "busy" | "skipped" | "refused"


def recheck(db: Session, *, alert_id: str, now: datetime, may_wait: bool) -> Outcome:
    """One waiting answer, looked at again. Commits.

    ``may_wait`` is whether the caller can come back in a moment: a sync of
    the same account already running answers ``busy`` while it may, and the
    figures are then read as they stand once it may not."""
    row = db.scalar(
        select(GuardAlert).where(GuardAlert.id == alert_id).with_for_update()
    )
    if row is None or row.closed_at is not None or row.pending_state != CHECKING_STATE:
        return "skipped"
    owner, account = row.owner, row.ad_account
    read = _read_today(db, owner=owner, account=account, now=now)
    if read == "busy" and may_wait:
        db.rollback()
        return "busy"
    try:
        check_pair(db, user=owner, row=row)
    except DomainError as refused:
        _close(row, now=now, why=str(refused))
        db.commit()
        return "refused"
    item = _item_of(db, row=row, account=account, now=now)
    if item is None:
        _close(row, now=now, why="")
        db.commit()
        return "gone"
    if read != "fresh":
        _ask_owner(row, item=item, now=now, unread=True)
        db.commit()
        return "confirm"
    if _still_true(row, item):
        try:
            carry_out(db, user=owner, row=row, answer=row.pending_answer, now=now)
        except DomainError as refused:
            logger.info(
                "guard_recheck_refused",
                extra={"alert": str(row.id), "why": type(refused).__name__},
            )
            row.pending_answer = row.pending_state = ""
            row.pending_at = None
            row.result, row.result_text = "failed", str(refused)
            db.commit()
            return "refused"
        db.commit()
        return "asked"
    _ask_owner(row, item=item, now=now, unread=False)
    db.commit()
    return "confirm"


def _read_today(
    db: Session, *, owner: object, account: AdAccount, now: datetime
) -> str:
    """``fresh`` when today's figures and the account were read within the
    hour - by the sweeps, or now; ``busy`` while a sync of the account runs;
    ``unread`` when Meta could not be read."""
    from app.modules.ads.exceptions import SyncAlreadyRunning
    from app.modules.ads.services.mirror import sync_ad_account
    from app.modules.metrics.services.sync import sync_today

    if fresh(db, owner=owner, account=account, now=now):  # type: ignore[arg-type]
        return "fresh"
    try:
        sync_ad_account(db, ad_account=account, whole=False)
        db.commit()
        sync_today(db, ad_account=account)
        db.commit()
    except SyncAlreadyRunning:
        db.rollback()
        return "busy"
    except Exception:
        db.rollback()
        logger.exception(
            "guard_recheck_read_failed", extra={"account": str(account.id)}
        )
        return "unread"
    db.expire_all()
    if fresh(db, owner=owner, account=account, now=now):  # type: ignore[arg-type]
        return "fresh"
    return "unread"


def _item_of(
    db: Session, *, row: GuardAlert, account: AdAccount, now: datetime
) -> Guarded | None:
    from app.modules.agent.services.run_guard import _baselines

    rows = list(
        db.scalars(
            select(GuardAlert)
            .where(
                GuardAlert.owner_id == row.owner_id,
                GuardAlert.ad_account_id == account.id,
            )
            .order_by(GuardAlert.created_at.desc())
        )
    )
    for item in guarded_groups(
        db, owner=row.owner, account=account, now=now, baselines=_baselines(rows)
    ):
        if item.group.adset_id == row.adset_external_id:
            return item
    return None


def _still_true(row: GuardAlert, item: Guarded) -> bool:
    """The same finding - the same kind about the same group or advert - by
    the guard's own rules on today's figures."""
    return any(
        finding.kind == row.kind
        and (finding.ad_id or finding.adset_id) == row.external_id
        for finding in judge(item.group)
    )


def _ask_owner(row: GuardAlert, *, item: Guarded, now: datetime, unread: bool) -> None:
    group = item.group
    spend, results = group.spend_minor, group.results
    if row.level == "ad":
        for advert in group.ads:
            if advert.ad_id == row.external_id:
                spend, results = advert.spend_minor, advert.results
    row.pending_state = CONFIRM_STATE
    row.pending_at = now
    row.now_figures = {
        "at": now.isoformat(),
        "day": item.day.isoformat(),
        "spend_minor": spend,
        "results": results,
        "usual_cost_minor": group.usual.cost_minor,
        "site_down": group.site_down,
        "unread": unread,
    }


def _close(row: GuardAlert, *, now: datetime, why: str) -> None:
    """Nothing to change: the group is not running, or not in a pair."""
    row.pending_answer = row.pending_state = ""
    row.pending_at = None
    row.result, row.result_text = "gone", why
    row.closed_at = now


def minutes_old(row: GuardAlert, *, at: datetime | None) -> int:
    from app.modules.agent.services.answer_guard import figures_at

    if at is None:
        return 0
    return max(int((at - figures_at(row)) / timedelta(minutes=1)), 0)


__all__ = ["minutes_old", "recheck"]
