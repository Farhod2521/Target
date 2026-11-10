from app.common.db import utcnow
from app.modules.sales.services import close_months, release_expired
from app.modules.sales.services.signup_sheet import sweep_signup_sheet
from app.worker import celery_app, task_session


@celery_app.task(queue="sync", ignore_result=True)
def release_expired_claims_task() -> int:
    with task_session() as db:
        return release_expired(db, now=utcnow())


@celery_app.task(queue="sync", ignore_result=True)
def close_sales_months_task() -> int:
    with task_session() as db:
        return len(close_months(db, now=utcnow()))


@celery_app.task(queue="webhooks", ignore_result=True)
def sweep_signup_sheet_task() -> int:
    """Every minute: sign-ups who did not pay in five minutes, to the sheet.

    Not on ``sync``: that queue lags behind Meta syncs, and the team wants
    the row a few minutes after the sign-up.
    """
    with task_session() as db:
        return sweep_signup_sheet(db, now=utcnow())
