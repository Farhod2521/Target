from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, String, UniqueConstraint, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.db import Base, utcnow


class CustomCategory(Base):
    __tablename__ = "business_custom_categories"
    __table_args__ = (
        UniqueConstraint('owner_id', 'label', name="custom_category_is_unique_per_owner"),
        CheckConstraint(text("NOT (label = '')"), name="custom_category_has_a_label"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    owner_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    label: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    preset_key: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    # -- django extras --
    owner: Mapped["User"] = relationship(foreign_keys=[owner_id], lazy="select")  # noqa: F821
