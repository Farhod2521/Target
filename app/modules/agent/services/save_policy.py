"""Turning the agent on, off, and adjusting how hard it presses."""

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.accounts.models import User
from app.modules.agent.models import AgentPolicy


def save_policy(db: Session, *, user: User, **values: Any) -> AgentPolicy:
    """Store this account's settings, creating the row on first save. Caller commits."""
    row = db.scalar(select(AgentPolicy).where(AgentPolicy.owner_id == user.id))
    if row is None:
        row = AgentPolicy(owner_id=user.id)
        db.add(row)
    for field, value in values.items():
        setattr(row, field, value)
    db.flush()
    return row


__all__ = ["save_policy"]
