from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, UniqueConstraint, Uuid
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.db import Base, Json, utcnow


class Ad(Base):
    __tablename__ = "ads"
    __table_args__ = (
        UniqueConstraint('provider', 'external_id', name="uniq_ad_per_provider"),
        Index("ads_owner_i_17e920_idx", 'owner_id', 'lead_form_external_id'),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    owner_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False, index=True, default="")
    external_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True, default="")
    name: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(Text, nullable=False, default="")
    effective_status: Mapped[str] = mapped_column(Text, nullable=False, default="")
    delivery: Mapped[str] = mapped_column(String(16), nullable=False, default='unknown')
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    adset_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("adsets.id", ondelete="CASCADE"), nullable=False, index=True)
    creative_external_id: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    lead_form_external_id: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    issues: Mapped[Any] = mapped_column(Json, nullable=False, default=list)
    issue_codes: Mapped[list[Any]] = mapped_column(ARRAY(String(32)), nullable=False, default=list)
    issue_summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    review_feedback: Mapped[Any] = mapped_column(Json, nullable=False, default=dict)
    # -- django extras --
    owner: Mapped["User"] = relationship(foreign_keys=[owner_id], lazy="select")  # noqa: F821
    adset: Mapped["AdSet"] = relationship(foreign_keys=[adset_id], lazy="select")  # noqa: F821
