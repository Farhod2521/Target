from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, SmallInteger, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.db import Base, Json, utcnow


class RawLeadEvent(Base):
    __tablename__ = "raw_lead_events"
    __table_args__ = (
        Index("raw_lead_ev_status_af44bf_idx", 'status', 'created_at'),
        Index("raw_lead_ev_provide_e911e7_idx", 'provider', 'leadgen_external_id'),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    provider: Mapped[str] = mapped_column(String(32), nullable=False, index=True, default="")
    payload: Mapped[Any] = mapped_column(Json, nullable=False, default=dict)
    signature_valid: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    page_external_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True, default="")
    leadgen_external_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True, default="")
    adset_external_id: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    owner_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default='received')
    attempts: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    processed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error_code: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    error_message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # -- django extras --
    owner: Mapped["User | None"] = relationship(foreign_keys=[owner_id], lazy="select")  # noqa: F821
