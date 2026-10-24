from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, LargeBinary, String, Text, UniqueConstraint, Uuid
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.db import Base, Json, utcnow


class SheetLink(Base):
    __tablename__ = "sheet_links"
    __table_args__ = (
        UniqueConstraint('owner_id', name="uniq_sheet_link_per_owner"),
        Index("sheet_links_status_77e8cb_idx", 'status', 'next_attempt_at'),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    owner_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default='preparing')
    broken_reason: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    mode: Mapped[str] = mapped_column(String(16), nullable=False, default='single')
    only_form_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("lead_forms.id", ondelete="RESTRICT"), nullable=True, index=True)
    google_email: Mapped[str] = mapped_column(String(254), nullable=False, default="")
    token_encrypted: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    token_fingerprint: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    scopes: Mapped[list[Any]] = mapped_column(ARRAY(String(128)), nullable=False, default=list)
    spreadsheet_id: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    sheet_id: Mapped[str] = mapped_column(String(32), nullable=False, default='')
    spreadsheet_url: Mapped[str] = mapped_column(Text, nullable=False, default="")
    columns: Mapped[Any] = mapped_column(Json, nullable=False, default=list)
    connected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deliver_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    broken_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    caught_up_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    next_attempt_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_code: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    # -- django extras --
    owner: Mapped["User"] = relationship(foreign_keys=[owner_id], lazy="select")  # noqa: F821
    only_form: Mapped["LeadForm | None"] = relationship(foreign_keys=[only_form_id], lazy="select")  # noqa: F821
