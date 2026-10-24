from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, Text, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.db import Base, Json, utcnow


class AgentSuggestion(Base):
    __tablename__ = "agent_suggestions"
    __table_args__ = (
        Index("uniq_pending_suggestion_per_object", 'owner_id', 'target_external_id', 'rule', unique=True, postgresql_where=text("status = 'pending'")),
        Index("agent_sugg_owner_status", 'owner_id', 'status', text("weight DESC")),
        Index("agent_sugg_expiry", 'status', 'expires_at'),
        Index("agent_sugg_review_due", 'status', 'review_at'),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    owner_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    target_provider: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    target_level: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    target_external_id: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    run_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("agent_runs.id", ondelete="RESTRICT"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(24), nullable=False, default="")
    rule: Mapped[str] = mapped_column(String(32), nullable=False, index=True, default="")
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    evidence: Mapped[Any] = mapped_column(Json, nullable=False, default=dict)
    payload: Mapped[Any] = mapped_column(Json, nullable=False, default=dict)
    weight: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    target_parent_id: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    cause: Mapped[str] = mapped_column(String(24), nullable=False, default="")
    diagnosis: Mapped[Any] = mapped_column(Json, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default='pending')
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decided_by_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    stale_reason: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    review_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    outcome: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    outcome_figures: Mapped[Any] = mapped_column(Json, nullable=False, default=dict)
    assessed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    action_log_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("action_logs.id", ondelete="SET NULL"), nullable=True, index=True)
    # -- django extras --
    owner: Mapped["User"] = relationship(foreign_keys=[owner_id], lazy="select")  # noqa: F821
    run: Mapped["AgentRun"] = relationship(foreign_keys=[run_id], lazy="select")  # noqa: F821
    decided_by: Mapped["User | None"] = relationship(foreign_keys=[decided_by_id], lazy="select")  # noqa: F821
    action_log: Mapped["ActionLog | None"] = relationship(foreign_keys=[action_log_id], lazy="select")  # noqa: F821

    def to_ref(self) -> "ExternalRef":  # noqa: F821
        """The three target columns as the one object every other layer passes."""
        from adskit import ExternalRef

        return ExternalRef(
            provider=self.target_provider,  # type: ignore[arg-type]
            level=self.target_level,  # type: ignore[arg-type]
            id=self.target_external_id,
        )
