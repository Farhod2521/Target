from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, SmallInteger, String, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.db import Base, Json, utcnow


class AgentRun(Base):
    __tablename__ = "agent_runs"
    __table_args__ = (
        Index("agent_runs_owner_date", 'owner_id', text("created_at DESC")),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    owner_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default='running')
    skip_reason: Mapped[str] = mapped_column(String(24), nullable=False, default="")
    source: Mapped[str] = mapped_column(String(16), nullable=False, default='night')
    window_days: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    considered: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    found: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    proposed: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    llm_cost_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="")
    advice: Mapped[Any] = mapped_column(Json, nullable=False, default=list)
    maturity: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    dropped: Mapped[Any] = mapped_column(Json, nullable=False, default=list)
    error_code: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # -- django extras --
    owner: Mapped["User"] = relationship(foreign_keys=[owner_id], lazy="select")  # noqa: F821
