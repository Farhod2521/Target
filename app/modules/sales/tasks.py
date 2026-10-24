from app.common.db import utcnow
from app.modules.sales.services import close_months, release_expired
from app.worker import celery_app, task_session


@celery_app.task(queue="sync", ignore_result=True)
def release_expired_claims_task() -> int:
    with task_session() as db:
        return release_expired(db, now=utcnow())


@celery_app.task(queue="sync", ignore_result=True)
def close_sales_months_task() -> int:
    with task_session() as db:
        return len(close_months(db, now=utcnow()))
