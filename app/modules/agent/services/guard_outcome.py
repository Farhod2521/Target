"""What the provider did with a change a guard finding asked for.

Called once a change's write is over (see
:func:`app.modules.ads.services.manage.apply_change`). The finding whose
stop - the guard's own - or answer - the owner's - the change was is told:

- landed: an answered stop or advert stop ends the finding; a lower budget
  leaves it open for the guard to watch;
- refused: the provider's reason, in the owner's words, is kept, and the
  buttons come back - nothing was changed.

The phone hears of it straight away (see
:func:`app.modules.notifications.services.announce_guard.show_state`).
"""

import uuid
from datetime import datetime
from functools import partial

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.common.db import on_commit
from app.modules.agent.guard_copy import STOP_REFUSED, STOP_REFUSED_WHY
from app.modules.agent.models import GuardAlert
from app.modules.agent.services.answer_guard import APPLIED, CLOSING, FAILED
from app.modules.audit.constants import ActionStatus
from app.modules.audit.models import ActionLog


def note_change_settled(db: Session, *, log_id: str, now: datetime) -> int:
    """Write the change's outcome on its finding. Returns the rows told. Commits."""
    try:
        pk = uuid.UUID(str(log_id))
    except ValueError:
        return 0
    log = db.get(ActionLog, pk)
    if log is None or log.status == ActionStatus.PENDING:
        return 0
    rows = list(
        db.scalars(
            select(GuardAlert)
            .where(or_(GuardAlert.answer_log_id == pk, GuardAlert.action_log_id == pk))
            .with_for_update()
        )
    )
    told = 0
    for row in rows:
        if settle(row, log=log, now=now):
            told += 1
            alert_id = str(row.id)
            on_commit(db, partial(_tell, alert_id))
    db.commit()
    return told


def settle(row: GuardAlert, *, log: ActionLog, now: datetime) -> bool:
    """The outcome on the row, once. Returns whether it changed."""
    from app.modules.ads.selectors.failures import failure_sentence

    if log.status == ActionStatus.PENDING:
        return False
    if (row.figures or {}).get("result_log_id") == str(log.id):
        return False
    if row.answer_log_id is not None and row.answer_log_id != log.id:
        # The guard's own stop, settled after the owner already answered it
        # with a change of their own: that change's outcome is the news.
        return False
    owners = row.answer_log_id == log.id
    applied = log.status == ActionStatus.APPLIED
    row.result = APPLIED if applied else FAILED
    row.result_text = "" if applied else failure_sentence(log)
    figures = {**(row.figures or {}), "result_log_id": str(log.id)}
    if not owners and not applied:
        # The guard's own stop refused: the row says so from now on, whatever
        # the owner answers it with.
        figures[STOP_REFUSED] = True
        figures[STOP_REFUSED_WHY] = row.result_text
    row.figures = figures
    if owners and applied and row.answer in CLOSING:
        row.closed_at = now
    return True


def _tell(alert_id: str) -> None:
    from app.modules.notifications.tasks import tell_guard_outcome_task

    tell_guard_outcome_task.delay(alert_id)


__all__ = ["note_change_settled", "settle"]
