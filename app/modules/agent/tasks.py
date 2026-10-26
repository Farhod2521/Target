"""Celery tasks for the agent: the nightly pass, diagnoses, fixes, verdicts,
the agent's own stops and the frequency levels.

Arguments are ids and plain values; the work is the services'. The
``*_all_*`` tasks fan out per owner and are what a periodic schedule calls.
"""

import logging
import uuid
from hashlib import md5

from sqlalchemy.orm import Session

from app.common.db import utcnow
from app.modules.accounts.models import User
from app.modules.agent.constants import AGENT_SPREAD_SECONDS
from app.modules.agent.exceptions import AgentAlreadyRunning
from app.modules.agent.selectors.launch_watch import owners_with_launches
from app.modules.agent.selectors.policy import (
    agent_owner_ids,
    owners_to_diagnose,
    owners_with_faults,
)
from app.modules.agent.selectors.suggestions import owners_with_outcomes_due
from app.modules.agent.services.assess_outcomes import assess_owner
from app.modules.agent.services.check_frequency import check_frequency
from app.modules.agent.services.diagnose_account import diagnose_account
from app.modules.agent.services.propose_fixes import propose_fixes
from app.modules.agent.services.release_stalled_runs import release_stalled_runs
from app.modules.agent.services.run_agent import run_agent
from app.modules.agent.services.stop_fruitless import stop_fruitless
from app.modules.integrations.constants import NIGHT_AGENT_HOUR, NIGHT_DIAGNOSIS_HOUR
from app.worker import celery_app, task_session

logger = logging.getLogger(__name__)


def _owner(db: Session, owner_id: str) -> User | None:
    try:
        return db.get(User, uuid.UUID(str(owner_id)))
    except ValueError:
        return None


def _stagger(owner_id: object) -> int:
    """How many seconds into the hour this account's pass starts."""
    digest = md5(str(owner_id).encode(), usedforsecurity=False).digest()
    return int.from_bytes(digest[:4], "big") % AGENT_SPREAD_SECONDS


@celery_app.task(queue="agent", ignore_result=True)
def run_agent_task(user_id: str) -> str:
    """One account's nightly pass. Returns a word for the task log."""
    with task_session() as db:
        user = _owner(db, user_id)
        if user is None:
            return "gone"
        try:
            run = run_agent(db, user=user)
        except AgentAlreadyRunning:
            logger.info("agent_run_locked", extra={"user": user_id})
            return "locked"
        if run is None:
            return "disabled"
        return f"{run.skip_reason or 'proposed'}:{run.proposed}"


@celery_app.task(queue="agent", ignore_result=True)
def run_all_agents() -> str:
    """Every account the agent is on for, once a night - its owner's."""
    from app.modules.integrations.selectors.watch import owners_at_hour

    with task_session() as db:
        now = utcnow()
        owners = owners_at_hour(
            db,
            owner_ids=agent_owner_ids(db, now=now),
            now=now,
            hour=NIGHT_AGENT_HOUR,
        )
    for owner_id in owners:
        run_agent_task.apply_async(args=[str(owner_id)], countdown=_stagger(owner_id))
    return f"queued:{len(owners)}"


@celery_app.task(queue="sync", ignore_result=True)
def release_stalled_runs_task() -> int:
    """Close the passes whose worker never came back. Returns how many."""
    with task_session() as db:
        return release_stalled_runs(db)


@celery_app.task(queue="agent", ignore_result=True)
def diagnose_account_task(owner_id: str) -> int:
    """One owner's causes for the night. Returns how many groups."""
    with task_session() as db:
        return diagnose_account(db, owner_id=owner_id, now=utcnow())


@celery_app.task(queue="agent", ignore_result=True)
def diagnose_all_accounts_task() -> int:
    """Queue every owner with an account to read, or rows left to clear."""
    from app.modules.integrations.selectors.watch import owners_at_hour

    with task_session() as db:
        owners = owners_at_hour(
            db,
            owner_ids=owners_to_diagnose(db),
            now=utcnow(),
            hour=NIGHT_DIAGNOSIS_HOUR,
        )
    for owner_id in owners:
        diagnose_account_task.delay(str(owner_id))
    return len(owners)


@celery_app.task(queue="agent", ignore_result=True)
def propose_fixes_task(owner_id: str) -> int:
    """One owner's fixes for what the provider stopped. Returns how many."""
    with task_session() as db:
        owner = _owner(db, owner_id)
        if owner is None:
            return 0
        return propose_fixes(db, owner=owner, now=utcnow())


@celery_app.task(queue="agent", ignore_result=True)
def propose_all_fixes() -> int:
    """Queue every owner with something stopped, after the half-hourly sync."""
    with task_session() as db:
        owners = owners_with_faults(db)
    for owner_id in owners:
        propose_fixes_task.delay(str(owner_id))
    return len(owners)


@celery_app.task(queue="agent", ignore_result=True)
def assess_outcomes_task(owner_id: str) -> int:
    """One owner's verdicts on the changes they approved. Returns how many."""
    with task_session() as db:
        owner = _owner(db, owner_id)
        if owner is None:
            return 0
        return assess_owner(db, owner=owner, now=utcnow())


@celery_app.task(queue="agent", ignore_result=True)
def assess_all_outcomes() -> int:
    """Queue every owner with a change whose aftermath can be read now."""
    with task_session() as db:
        owners = owners_with_outcomes_due(db, now=utcnow())
    for owner_id in owners:
        assess_outcomes_task.delay(str(owner_id))
    return len(owners)


@celery_app.task(queue="agent", ignore_result=True)
def stop_fruitless_task(owner_id: str) -> int:
    """One owner's groups that spend with nothing back. Returns how many."""
    with task_session() as db:
        owner = _owner(db, owner_id)
        if owner is None:
            return 0
        return stop_fruitless(db, owner=owner, now=utcnow())


@celery_app.task(queue="agent", ignore_result=True)
def stop_all_fruitless() -> int:
    """Queue every owner the agent runs for who launched anything here."""
    with task_session() as db:
        owners = agent_owner_ids(db, now=utcnow()) & owners_with_launches(db)
    for owner_id in owners:
        stop_fruitless_task.delay(str(owner_id))
    return len(owners)


@celery_app.task(queue="agent", ignore_result=True)
def check_frequency_task(owner_id: str) -> int:
    """One owner's frequency levels for the night. Returns how many were raised.

    The Django project calls this from the notifications app, which then
    sends what was raised; here the raise is the agent's and the message is
    left to whoever reads the ``agent.frequency_alerted`` events.
    """
    with task_session() as db:
        owner = _owner(db, owner_id)
        if owner is None:
            return 0
        return len(check_frequency(db, owner=owner, now=utcnow()))


@celery_app.task(queue="agent", ignore_result=True)
def check_all_frequency() -> int:
    """Queue every owner the agent runs for who launched anything here."""
    with task_session() as db:
        owners = agent_owner_ids(db, now=utcnow()) & owners_with_launches(db)
    for owner_id in owners:
        check_frequency_task.delay(str(owner_id))
    return len(owners)
