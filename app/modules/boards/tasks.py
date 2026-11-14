from app.common.db import utcnow
from app.modules.boards.triggers import sweep_idle, sweep_sales, sweep_support
from app.worker import celery_app, task_session


@celery_app.task(queue="webhooks", ignore_result=True)
def sweep_sales_board_task() -> int:
    """Every minute: new sign-ups become leads, paid ones go to Sotildi.

    On ``webhooks`` like the sign-up sheet: ``sync`` lags behind Meta syncs.
    """
    with task_session() as db:
        opened, sold = sweep_sales(db, now=utcnow())
        return opened + sold


@celery_app.task(queue="webhooks", ignore_result=True)
def sweep_support_board_task() -> int:
    """Every minute: setup undone an hour after paying, Sales' «Support
    kerak» on payment, and Meta's refusals become the client's ticket."""
    with task_session() as db:
        return sweep_support(db, now=utcnow())


@celery_app.task(queue="webhooks", ignore_result=True)
def sweep_idle_board_task() -> int:
    """Every hour: paid clients with no ad switched on in three days, and
    running campaigns that spent nothing in a day, become tickets."""
    with task_session() as db:
        return sweep_idle(db, now=utcnow())


@celery_app.task(queue="webhooks", ignore_result=True)
def sweep_renewal_board_task() -> int:
    """Every minute: paying Standart and Pro terms that run out become
    cards, an ended term, a bill and a payment move them."""
    from app.modules.boards import renewal

    with task_session() as db:
        return renewal.sweep(db, now=utcnow())
