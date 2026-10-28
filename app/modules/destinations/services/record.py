"""The audit trail for the three things a person does to their link.

Each press is written ``PENDING``; the worker that does what it asked of
Google closes it. Nothing here commits: the caller's transaction does.
"""

import uuid
from collections.abc import Sequence
from datetime import datetime
from typing import Any

from googlekit import GoogleError
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.audit.constants import ActionStatus, ActionType, ActorType, EventName
from app.modules.audit.models import ActionLog
from app.modules.audit.services import emit
from app.modules.destinations.constants import (
    AUDIT_AGGREGATE,
    AUDIT_LEVEL,
    AUDIT_PROVIDER,
    SUPERSEDED,
)
from app.modules.destinations.models import SheetLink


def record_action(
    db: Session,
    *,
    user: User,
    link: SheetLink,
    action: ActionType,
    event: EventName,
    previous: dict[str, Any],
    now: datetime,
) -> ActionLog:
    """One pending ActionLog row and one outbox event. No token, no email."""
    _supersede(db, link=link, now=now)
    log = ActionLog(
        owner_id=user.id,
        actor_type=ActorType.USER,
        actor_id=user.id,
        action=action,
        target_provider=AUDIT_PROVIDER,
        target_level=AUDIT_LEVEL,
        target_external_id=link.spreadsheet_id,
        request_payload={},
        previous_state=previous,
        result_payload={},
        dropped=[],
        status=ActionStatus.PENDING,
        dry_run=False,
        idempotency_key=f"{action}:{uuid.uuid4().hex}",
    )
    db.add(log)
    db.flush()
    emit(
        db,
        owner_id=user.id,
        name=event,
        aggregate_type=AUDIT_AGGREGATE,
        aggregate_id=link.id,
        payload={"action_log_id": str(log.id)},
        occurred_at=now,
    )
    return log


def close_actions(
    db: Session, *, link: SheetLink, actions: Sequence[ActionType], now: datetime
) -> int:
    """Google did what these presses asked. The target becomes the file as it is."""
    return _pending(
        db,
        link=link,
        actions=actions,
        status=ActionStatus.APPLIED,
        target_external_id=link.spreadsheet_id,
        applied_at=now,
        updated_at=now,
    )


def fail_actions(
    db: Session,
    *,
    link: SheetLink,
    actions: Sequence[ActionType],
    error: GoogleError,
    now: datetime,
) -> int:
    """Google refused what these presses asked: the class, never its words."""
    return refuse_actions(
        db, link=link, actions=actions, code=type(error).__name__, now=now
    )


def refuse_actions(
    db: Session,
    *,
    link: SheetLink,
    actions: Sequence[ActionType],
    code: str,
    now: datetime,
) -> int:
    """These presses cannot be done, for the reason ``code`` names."""
    return _pending(
        db,
        link=link,
        actions=actions,
        status=ActionStatus.FAILED,
        error_code=code,
        updated_at=now,
    )


def _supersede(db: Session, *, link: SheetLink, now: datetime) -> None:
    """Close a press still open from before: the new one decides the link."""
    _pending(
        db,
        link=link,
        actions=(),
        status=ActionStatus.FAILED,
        error_code=SUPERSEDED,
        updated_at=now,
    )


def _pending(
    db: Session, *, link: SheetLink, actions: Sequence[ActionType], **values: Any
) -> int:
    """Update this link's presses still waiting for a worker - of ``actions``, or any."""
    query = update(ActionLog).where(
        ActionLog.owner_id == link.owner_id,
        ActionLog.target_provider == AUDIT_PROVIDER,
        ActionLog.target_level == AUDIT_LEVEL,
        ActionLog.status == ActionStatus.PENDING,
    )
    if actions:
        query = query.where(ActionLog.action.in_([str(a) for a in actions]))
    result = db.execute(
        query.values(**values).execution_options(synchronize_session=False)
    )
    return int(getattr(result, "rowcount", 0) or 0)


__all__ = ["close_actions", "fail_actions", "record_action", "refuse_actions"]
