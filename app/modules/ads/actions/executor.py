"""Carrying out one pending change: the steps every write to a provider shares.

Three kinds of write used to run three copies of these steps - a switch or a
budget (``manage``), a delete (``removal``), a new version of an advert
(``swap``) - and the copies drifted: one recorded the provider's raw code
where the others recorded the screen's word, one could leave a row PENDING
on an unexpected error. Here the steps run once, in one order, and a kind of
write supplies only what is its own: the check before, the write, what to
keep afterwards.

The order is the safety. The audit row is read and claimed first, so a
second worker finds it done; the object and the account's token come from the
mirror; the provider is asked for the object's state before anything is
written, so a guardrail decides on what is true now rather than on what the
mirror last saw; and every refusal, expected or not, closes the row - a row
left PENDING locks every switch on that object until the stale window passes.
"""

import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from adskit import ExternalRef, registry
from adskit.dto import ActionResult, StatusDTO
from adskit.errors import AccountActionRequired, ProviderError
from sqlalchemy.orm import Session

from app.common.config import settings
from app.modules.ads.exceptions import ConnectionUnusable, NoAdAccount
from app.modules.ads.selectors import managed_target
from app.modules.ads.services.access import target_account_and_token
from app.modules.ads.services.manage import fail_log, refused_by_provider
from app.modules.audit.constants import ActionStatus
from app.modules.audit.models import ActionLog

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class Job:
    """One change being carried out, and everything read for it so far."""

    log: ActionLog
    target: Any
    account: Any
    token: str
    ref: ExternalRef
    provider: Any
    dry_run: bool
    before: StatusDTO | None = None
    # What a kind of write found while checking and needs again while writing.
    found: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Write:
    """What one kind of write supplies; the rest is :func:`carry_out`'s.

    ``ready`` runs before the account is touched and answers a refusal word
    for an object that cannot be written at all; ``check`` runs on the
    provider's state and answers one for a change the guardrails refuse now;
    ``write`` makes the calls; ``finish`` keeps what came of them.
    """

    actions: frozenset[str]
    write: Callable[[Session, Job], ActionResult]
    finish: Callable[[Session, Job, ActionResult], None]
    check: Callable[[Session, Job], str] = lambda _db, _job: ""
    ready: Callable[[Session, ActionLog, Any], str] = lambda _db, _log, _target: ""
    reads_before: bool = True


def carry_out(db: Session, *, log_id: str, kind: Write) -> str:
    """One audit row, carried out. Returns a word for the task's log line."""
    try:
        log = db.get(ActionLog, uuid.UUID(str(log_id)))
    except ValueError:
        log = None
    if log is None:
        return "gone"
    if log.status != ActionStatus.PENDING:
        return "done"
    if log.action not in kind.actions:
        fail_log(db, log=log, code="unknown", message=f"no write for {log.action}")
        return "unknown"
    target = managed_target(
        db, owner=log.owner, level=log.target_level, external_id=log.target_external_id
    )
    if target is None:
        fail_log(db, log=log, code="gone", message="object is no longer in the mirror")
        return "gone"
    unready = kind.ready(db, log, target)
    if unready:
        fail_log(db, log=log, code=unready, message="the object cannot be written")
        return "refused"
    try:
        account, token = target_account_and_token(target=target, level=log.target_level)
    except (NoAdAccount, ConnectionUnusable) as exc:
        fail_log(db, log=log, code="connection", message=exc.message)
        return "unusable"
    try:
        provider = registry.get(log.target_provider)
    except Exception as exc:
        logger.exception("no provider for change %s", log.id)
        fail_log(db, log=log, code="unknown", message=str(exc))
        return "failed"
    job = Job(
        log=log,
        target=target,
        account=account,
        token=token,
        ref=ExternalRef(
            provider=log.target_provider,
            level=log.target_level,
            id=log.target_external_id,
        ),
        provider=provider,
        dry_run=bool(settings.ads_dry_run),
    )
    try:
        if kind.reads_before:
            job.before = provider.campaigns.get_status(ref=job.ref, token=token)
        refusal = kind.check(db, job)
    except ProviderError as exc:
        _refused(db, job=job, exc=exc)
        return "failed"
    except Exception as exc:
        logger.exception("change %s could not be prepared", log.id)
        fail_log(db, log=log, code="unknown", message=str(exc))
        return "failed"
    if refusal:
        fail_log(db, log=log, code=refusal, message="the check before the write failed")
        return "refused"
    try:
        result = kind.write(db, job)
    except ProviderError as exc:
        _refused(db, job=job, exc=exc)
        return "failed"
    except Exception as exc:
        logger.exception("change %s failed unexpectedly", log.id)
        fail_log(db, log=log, code="unknown", message=str(exc))
        return "failed"
    if not result.ok:
        # Answered and refused without raising: nothing changed, so the row
        # must not say it did.
        fail_log(db, log=log, code="not_applied", message=str(result.raw_response))
        return "failed"
    kind.finish(db, job, result)
    db.commit()
    return "applied"


def _refused(db: Session, *, job: Job, exc: ProviderError) -> None:
    """The provider's refusal, under the word the screens read."""
    if isinstance(exc, AccountActionRequired):
        from app.modules.integrations.services import note_action_required

        note_action_required(db, connection=job.account.connection)
    refused_by_provider(
        db,
        log=job.log,
        exc=exc,
        account=job.account,
        port=job.provider.campaigns,
        token=job.token,
    )


__all__ = ["Job", "Write", "carry_out"]
