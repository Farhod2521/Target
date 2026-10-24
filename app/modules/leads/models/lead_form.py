from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.db import Base, Json, utcnow


class LeadForm(Base):
    __tablename__ = "lead_forms"
    __table_args__ = (
        UniqueConstraint('owner_id', 'provider', 'external_id', name="uniq_lead_form_per_owner"),
        Index("lead_forms_provide_c91a0b_idx", 'provider', 'external_id'),
        Index("lead_forms_owner_i_ca50ba_idx", 'owner_id', 'status'),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    owner_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False, index=True, default="")
    external_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True, default="")
    page_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("page_accounts.id", ondelete="RESTRICT"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    questions_raw: Mapped[Any] = mapped_column(Json, nullable=False, default=list)
    privacy_policy_url: Mapped[str] = mapped_column(String(1000), nullable=False, default="")
    locale: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    ending: Mapped[Any] = mapped_column(Json, nullable=False, default=dict)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default='ACTIVE')
    status_raw: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    leads_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    swept_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # -- django extras --
    page: Mapped["PageAccount"] = relationship(foreign_keys=[page_id], lazy="select")  # noqa: F821
    owner: Mapped["User"] = relationship(foreign_keys=[owner_id], lazy="select")  # noqa: F821
