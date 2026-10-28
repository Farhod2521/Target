"""The audit row and the outbox row every support write leaves."""

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.audit.constants import ActionStatus, ActionType, ActorType, EventName
from app.modules.audit.models import ActionLog
from app.modules.audit.services import emit
from app.modules.supportchat.constants import (
    ACTION_TARGET_LEVEL,
    ACTION_TARGET_PROVIDER,
)
from app.modules.supportchat.models import SupportConversation


def journal(
    db: Session,
    *,
    conversation: SupportConversation,
    actor: User,
    action: ActionType,
    event: EventName,
    payload: dict[str, Any],
    previous_state: dict[str, Any],
    key: str,
    now: datetime,
) -> None:
    """Write both rows for one support write, in the caller's transaction."""
    db.add(
        ActionLog(
            owner_id=conversation.owner_id,
            actor_type=ActorType.USER,
            actor_id=actor.id,
            target_provider=ACTION_TARGET_PROVIDER,
            target_level=ACTION_TARGET_LEVEL,
            target_external_id=str(conversation.id),
            action=action,
            request_payload=payload,
            previous_state=previous_state,
            idempotency_key=key,
            status=ActionStatus.APPLIED,
            dry_run=False,
        )
    )
    emit(
        db,
        owner_id=conversation.owner_id,
        name=event,
        aggregate_type="support_conversation",
        aggregate_id=conversation.id,
        payload=payload | {"actor_id": str(actor.id)},
        occurred_at=now,
    )
