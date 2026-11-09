"""Celery tasks for delivering leads to the owner's spreadsheet and to a
Telegram group or channel.

The spreadsheet has no retries: the minute sweep is every retry there is.
A Telegram post waits as long as Telegram asks and tries again; what is
still left after that the sweep posts.
"""

from celery import Task
from celery.exceptions import MaxRetriesExceededError

from app.common.db import utcnow
from app.modules.destinations.constants import LEAD_POST_RETRIES
from app.modules.destinations.services import (
    check_sheet_link,
    deliver_to_sheet,
    prepare_sheet,
    revoke_sheet_token,
    sweep_sheet_checks,
    sweep_sheets,
)
from app.modules.destinations.services.lead_chats import (
    check_lead_chats,
    post_lead,
    sweep_lead_posts,
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


@celery_app.task(
    bind=True, queue="webhooks", ignore_result=True, max_retries=LEAD_POST_RETRIES
)
def post_lead_task(self: Task, lead_id: str) -> str:
    """One lead into its pair's group or channel. A wait Telegram asked for
    is a retry later, never a worker asleep."""
    with task_session() as db:
        outcome = post_lead(db, lead_id=lead_id, now=utcnow())
    if isinstance(outcome, str):
        return outcome
    try:
        raise self.retry(countdown=outcome)
    except MaxRetriesExceededError:
        return "left_for_sweep"


@celery_app.task(queue="webhooks", ignore_result=True)
def sweep_lead_posts_task() -> int:
    """Every few minutes: the chats due a look, then the posts a lost task
    or a long outage left."""
    with task_session() as db:
        check_lead_chats(db, now=utcnow())
        return sweep_lead_posts(db, now=utcnow())
