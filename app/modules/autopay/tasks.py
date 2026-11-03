from app.common.db import utcnow
from app.modules.autopay.services import charge_due
from app.worker import celery_app, task_session


@celery_app.task(queue="sync", ignore_result=True)
def charge_due_task() -> int:
    with task_session() as db:
        return charge_due(db, now=utcnow())
