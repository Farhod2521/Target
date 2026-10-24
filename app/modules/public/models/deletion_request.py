from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, Text, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.db import Base, utcnow


class DeletionRequest(Base):
    __tablename__ = "deletion_requests"
    __table_args__ = (
        CheckConstraint(text("(NOT (email = '')) OR (NOT (meta_user_id = ''))"), name="deletion_request_has_an_identifier"),
        Index("deletion_re_status_69cf50_idx", 'status', 'created_at'),
        Index("deletion_re_meta_us_2b644d_idx", 'meta_user_id'),
        Index("deletion_re_email_41023b_idx", 'email'),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    confirmation_code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, default="")
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default='received')
    email: Mapped[str] = mapped_column(String(254), nullable=False, default="")
    meta_user_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    owner_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # -- django extras --
    owner: Mapped["User | None"] = relationship(foreign_keys=[owner_id], lazy="select")  # noqa: F821
    @property
    def is_open(self) -> bool:
        return self.status in {"received", "in_progress"}
