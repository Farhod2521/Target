from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.db import Base, utcnow


class ConsultRequest(Base):
    __tablename__ = "consult_requests"
    __table_args__ = (
        Index("consult_req_contact_80a755_idx", 'contacted_at', text("created_at DESC")),
        Index("consult_req_phone_e_563acf_idx", 'phone_e164'),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    name: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    phone_e164: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    language: Mapped[str] = mapped_column(String(8), nullable=False, default="")
    contacted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    contacted_by_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    # -- django extras --
    contacted_by: Mapped["User | None"] = relationship(foreign_keys=[contacted_by_id], lazy="select")  # noqa: F821
