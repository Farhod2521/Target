import logging
from datetime import timedelta

from app.common.db import utcnow
from app.modules.telephony import calls, live, utel
from app.modules.telephony.constants import BACKFILL_HOURS
from app.worker import celery_app, task_session

logger = logging.getLogger(__name__)


@celery_app.task(queue="webhooks", ignore_result=True)
def backfill_calls_task(hours: int = BACKFILL_HOURS) -> int:
    """Every hour, and once on connecting: the calls of the last hours are
    read from UTeL's own history, for a hook that never came. UTeL does not
    say whether it sends a failed one again."""
    kept = 0
    with task_session() as db:
        now = utcnow()
        for connection in calls.connections(db):
            try:
                kept += calls.backfill(
                    db,
                    connection=connection,
                    since=now - timedelta(hours=hours),
                    now=now,
                )
            except (utel.Refused, utel.Unreachable) as exc:
                db.rollback()
                logger.warning(
                    "telephony: history of %s not read: %s",
                    connection.tenant,
                    type(exc).__name__,
                )
    return kept


@celery_app.task(queue="webhooks", ignore_result=True)
def forget_hook_events_task() -> int:
    """Every night: raw events older than two weeks go, and calls whose end
    never reached us leave the live picture."""
    with task_session() as db:
        live.forget_stale(db, now=utcnow())
        return calls.forget_old_events(db, now=utcnow())
