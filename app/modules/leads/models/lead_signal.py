from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, SmallInteger, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.db import Base, utcnow


class LeadSignal(Base):
    __tablename__ = "lead_signals"
    __table_args__ = (
        UniqueConstraint("lead_id", "stage", name="uniq_signal_per_stage"),
        Index("lead_signals_owner_status_idx", "owner_id", "status"),
        Index("lead_signals_status_occurred_idx", "status", "occurred_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    owner_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    lead_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("leads.id", ondelete="CASCADE"), nullable=False, index=True)
    ad_account_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("ad_accounts.id", ondelete="CASCADE"), nullable=False, index=True)
    stage: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    value_minor: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempts: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    dataset_id: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    trace_id: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    last_error: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    lead: Mapped["Lead"] = relationship(foreign_keys=[lead_id], lazy="select")  # noqa: F821
