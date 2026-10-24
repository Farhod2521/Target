from app.common.db import utcnow
from app.modules.audit.services import purge_errors, report_unresolved_actions
from app.worker import celery_app, task_session


@celery_app.task(queue="sync", ignore_result=True)
def report_unresolved_actions_task() -> int:
    with task_session() as db:
        return report_unresolved_actions(db, now=utcnow())


@celery_app.task(queue="sync", ignore_result=True)
def purge_errors_task() -> int:
    with task_session() as db:
        return purge_errors(db, now=utcnow())
