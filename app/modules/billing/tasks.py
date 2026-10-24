from app.common.db import utcnow
from app.modules.billing.services import expire_invoices, release_stale_holds
from app.worker import celery_app, task_session


@celery_app.task(queue="sync", ignore_result=True)
def expire_invoices_task() -> int:
    with task_session() as db:
        return expire_invoices(db, now=utcnow())


@celery_app.task(queue="sync", ignore_result=True)
def release_stale_holds_task() -> int:
    with task_session() as db:
        return release_stale_holds(db, now=utcnow())
