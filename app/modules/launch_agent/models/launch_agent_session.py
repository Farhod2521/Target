from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.common.db import Base, Json, utcnow


class LaunchAgentSession(Base):
    """One conversation of the advert chat.

    ``brief`` is what has been learned so far (``core.launch_agent.Brief``
    as a mapping) and ``messages`` what was said, oldest first. The launch
    it fills is the wizard's own row: the conversation only ever writes the
    answers the first screen writes.
    """

    __tablename__ = "launch_agent_sessions"
    __table_args__ = (
        Index("launch_agent_sessions_owner_status", "owner_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    owner_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    business_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("businesses.id", ondelete="SET NULL"), nullable=True, index=True)
    launch_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("campaign_launches.id", ondelete="SET NULL"), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(12), nullable=False, default="open")
    brief: Mapped[dict[str, Any]] = mapped_column(Json, nullable=False, default=dict)
    messages: Mapped[list[Any]] = mapped_column(Json, nullable=False, default=list)
    turns: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    heard_calls: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
