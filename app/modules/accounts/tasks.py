"""Accounts' work done off the request."""

from app.modules.accounts.services import mail_password_reset
from app.worker import celery_app, task_session


@celery_app.task(queue="webhooks", ignore_result=True)
def mail_password_reset_task(email: str) -> bool:
    """The new-password letter, sent from here so the page that asked answers
    as fast for an unknown address as for a known one."""
    with task_session() as db:
        return mail_password_reset(db, email=email)
