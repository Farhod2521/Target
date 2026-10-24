from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, UniqueConstraint, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.db import Base, Json, utcnow


class Lead(Base):
    __tablename__ = "leads"
    __table_args__ = (
        UniqueConstraint('provider', 'leadgen_id', name="uniq_lead_per_provider"),
        Index("leads_owner_i_d4669b_idx", 'owner_id', text("submitted_at DESC")),
        Index("leads_owner_i_dbd35e_idx", 'owner_id', 'adset_external_id', 'submitted_at'),
        Index("leads_owner_i_9393b9_idx", 'owner_id', 'is_test', text("submitted_at DESC")),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    owner_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    field_data_raw: Mapped[Any] = mapped_column(Json, nullable=False, default=list)
    answers: Mapped[Any] = mapped_column(Json, nullable=False, default=dict)
    raw_event_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("raw_lead_events.id", ondelete="SET NULL"), nullable=True, index=True)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    phone_e164: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    email: Mapped[str] = mapped_column(String(254), nullable=False, default="")
    city: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    provider: Mapped[str] = mapped_column(String(32), nullable=False, index=True, default="")
    form_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("lead_forms.id", ondelete="RESTRICT"), nullable=True, index=True)
    campaign_external_id: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    adset_external_id: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    ad_external_id: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    leadgen_id: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    is_test: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_organic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    anonymized_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # -- django extras --
    form: Mapped["LeadForm | None"] = relationship(foreign_keys=[form_id], lazy="select")  # noqa: F821
    raw_event: Mapped["RawLeadEvent | None"] = relationship(foreign_keys=[raw_event_id], lazy="select")  # noqa: F821
    owner: Mapped["User"] = relationship(foreign_keys=[owner_id], lazy="select")  # noqa: F821
