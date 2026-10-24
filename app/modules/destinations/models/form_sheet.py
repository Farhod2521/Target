from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.db import Base, Json, utcnow


class FormSheet(Base):
    __tablename__ = "form_sheets"
    __table_args__ = (
        UniqueConstraint('owner_id', 'form_id', name="uniq_form_sheet_per_form"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    owner_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    form_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("lead_forms.id", ondelete="RESTRICT"), nullable=True, index=True)
    spreadsheet_id: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    sheet_id: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    spreadsheet_url: Mapped[str] = mapped_column(Text, nullable=False, default="")
    columns: Mapped[Any] = mapped_column(Json, nullable=False, default=list)
    # -- django extras --
    owner: Mapped["User"] = relationship(foreign_keys=[owner_id], lazy="select")  # noqa: F821
    form: Mapped["LeadForm | None"] = relationship(foreign_keys=[form_id], lazy="select")  # noqa: F821
