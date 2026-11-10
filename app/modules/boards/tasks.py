from app.common.db import utcnow
from app.modules.boards.triggers import sweep_sales
from app.worker import celery_app, task_session


@celery_app.task(queue="webhooks", ignore_result=True)
def sweep_sales_board_task() -> int:
    """Every minute: new sign-ups become leads, paid ones go to Sotildi.

    On ``webhooks`` like the sign-up sheet: ``sync`` lags behind Meta syncs.
    """
    with task_session() as db:
        opened, sold = sweep_sales(db, now=utcnow())
        return opened + sold
