from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, SmallInteger, String, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column

from app.common.db import Base, utcnow
from app.common.i18n import get_language


class BusinessCategory(Base):
    __tablename__ = "business_categories"
    __table_args__ = (
        CheckConstraint(text("NOT (label_uz = '')"), name="business_category_has_a_name"),
        CheckConstraint(text("NOT (preset_key = '')"), name="business_category_has_a_preset"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, default="")
    label_uz: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    label_ru: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    label_en: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    preset_key: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    position: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # -- django extras --
    @property
    def label(self) -> str:
        by_language = {"ru": self.label_ru, "en": self.label_en}
        return by_language.get(get_language() or "", "") or self.label_uz

    def __str__(self) -> str:
        return self.label
