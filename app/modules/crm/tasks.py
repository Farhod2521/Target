from app.common.db import utcnow
from app.modules.crm.services import place_lead, sweep_unplaced
from app.worker import celery_app, task_session


@celery_app.task(queue="webhooks")
def place_lead_task(lead_id: str) -> str:
    with task_session() as db:
        return place_lead(db, lead_id=lead_id)


@celery_app.task(queue="webhooks")
def sweep_unplaced_task() -> int:
    with task_session() as db:
        return sweep_unplaced(db, now=utcnow())
