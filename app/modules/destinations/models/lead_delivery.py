from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.db import Base, utcnow


class LeadDelivery(Base):
    __tablename__ = "lead_deliveries"
    __table_args__ = (
        UniqueConstraint('lead_id', 'channel', name="uniq_delivery_per_lead_channel"),
        Index("lead_delive_owner_i_e2408a_idx", 'owner_id', 'channel', 'status'),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    owner_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    lead_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("leads.id", ondelete="CASCADE"), nullable=False, index=True)
    channel: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    form_sheet_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("form_sheets.id", ondelete="CASCADE"), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    sent_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # -- django extras --
    owner: Mapped["User"] = relationship(foreign_keys=[owner_id], lazy="select")  # noqa: F821
    lead: Mapped["Lead"] = relationship(foreign_keys=[lead_id], lazy="select")  # noqa: F821
    form_sheet: Mapped["FormSheet | None"] = relationship(foreign_keys=[form_sheet_id], lazy="select")  # noqa: F821
