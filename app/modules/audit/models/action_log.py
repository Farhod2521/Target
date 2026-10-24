from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.db import Base, Json, utcnow


class ActionLog(Base):
    __tablename__ = "action_logs"
    __table_args__ = (
        Index("action_logs_owner_i_8548e2_idx", 'owner_id', text("created_at DESC")),
        Index("action_logs_owner_i_97a329_idx", 'owner_id', 'target_external_id', text("created_at DESC")),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    owner_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    target_provider: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    target_level: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    target_external_id: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    actor_type: Mapped[str] = mapped_column(String(8), nullable=False, default="")
    actor_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    run_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("agent_runs.id", ondelete="SET NULL"), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    request_payload: Mapped[Any] = mapped_column(Json, nullable=False, default=dict)
    previous_state: Mapped[Any] = mapped_column(Json, nullable=False, default=dict)
    result_payload: Mapped[Any] = mapped_column(Json, nullable=False, default=dict)
    dropped: Mapped[Any] = mapped_column(Json, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default='pending')
    dry_run: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    idempotency_key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, default="")
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    error_code: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    error_message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reverted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # -- django extras --
    owner: Mapped["User"] = relationship(foreign_keys=[owner_id], lazy="select")  # noqa: F821
    actor: Mapped["User | None"] = relationship(foreign_keys=[actor_id], lazy="select")  # noqa: F821
    run: Mapped["AgentRun | None"] = relationship(foreign_keys=[run_id], lazy="select")  # noqa: F821
