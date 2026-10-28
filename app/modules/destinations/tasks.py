"""Celery tasks for delivering leads to the owner's spreadsheet.

No retries: the minute sweep is every retry there is.
"""

from app.common.db import utcnow
from app.modules.destinations.services import (
    check_sheet_link,
    deliver_to_sheet,
    prepare_sheet,
    revoke_sheet_token,
    sweep_sheet_checks,
    sweep_sheets,
)
from app.worker import celery_app, task_session


@celery_app.task(queue="sync", ignore_result=True)
def sweep_sheets_task() -> int:
    """Every minute: queue a run for each link with something to do."""
    with task_session() as db:
        return sweep_sheets(db, now=utcnow())


@celery_app.task(queue="sync", ignore_result=True)
def deliver_to_sheet_task(link_id: str) -> str:
    """One link's run. Locked per link inside the service."""
    with task_session() as db:
        return deliver_to_sheet(db, link_id=link_id)


@celery_app.task(queue="webhooks", ignore_result=True)
def prepare_sheet_task(link_id: str) -> str:
    """Make the file. On the fast queue: somebody is watching a screen for it."""
    with task_session() as db:
        return prepare_sheet(db, link_id=link_id)


@celery_app.task(queue="sync", ignore_result=True)
def revoke_sheet_token_task(link_id: str) -> str:
    """Hand a disconnected link's permission back to Google."""
    with task_session() as db:
        return revoke_sheet_token(db, link_id=link_id)


@celery_app.task(queue="sync", ignore_result=True)
def check_sheet_links_task() -> int:
    """Daily: queue a check for every link, and every revocation still owed."""
    with task_session() as db:
        return sweep_sheet_checks(db)


@celery_app.task(queue="sync", ignore_result=True)
def check_sheet_link_task(link_id: str) -> str:
    """One link's daily check."""
    with task_session() as db:
        return check_sheet_link(db, link_id=link_id)
