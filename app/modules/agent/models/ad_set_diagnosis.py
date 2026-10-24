from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import Date, DateTime, ForeignKey, Index, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.db import Base, Json, utcnow


class AdSetDiagnosis(Base):
    __tablename__ = "agent_diagnoses"
    __table_args__ = (
        UniqueConstraint('owner_id', 'provider', 'adset_external_id', name="uniq_diagnosis_per_adset"),
        Index("agent_diag_owner_cause", 'owner_id', 'cause'),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    owner_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    adset_external_id: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    name: Mapped[str] = mapped_column(Text, nullable=False, default="")
    cause: Mapped[str] = mapped_column(String(24), nullable=False, default="")
    signals: Mapped[Any] = mapped_column(Json, nullable=False, default=list)
    evidence: Mapped[Any] = mapped_column(Json, nullable=False, default=dict)
    since: Mapped[date] = mapped_column(Date, nullable=False)
    until: Mapped[date] = mapped_column(Date, nullable=False)
    diagnosed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # -- django extras --
    owner: Mapped["User"] = relationship(foreign_keys=[owner_id], lazy="select")  # noqa: F821
