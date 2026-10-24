from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, SmallInteger, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.db import Base, utcnow


class AgentPolicy(Base):
    __tablename__ = "agent_policies"
    __table_args__ = (
        UniqueConstraint('owner_id', name="uniq_agent_policy_per_owner"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    owner_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    self_repair: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    window_days: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=7)
    cooldown_hours: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=48)
    max_per_run: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=3)
    budget_step_pct: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=20)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # -- django extras --
    owner: Mapped["User"] = relationship(foreign_keys=[owner_id], lazy="select")  # noqa: F821
