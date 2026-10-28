from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Index, SmallInteger, String, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.db import Base, utcnow
from app.common.i18n import get_language


class GeoArea(Base):
    __tablename__ = "geo_areas"
    __table_args__ = (
        CheckConstraint(text("NOT (name_uz = '')"), name="geo_area_has_a_name"),
        CheckConstraint(text("NOT (country_code = '')"), name="geo_area_has_a_country"),
        CheckConstraint(text("NOT ((kind = 'region') AND (parent_id IS NOT NULL))"), name="geo_area_region_has_no_parent"),
        Index("geo_areas_country_815a19_idx", 'country_code', 'is_active', 'position'),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    key: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, default="")
    country_code: Mapped[str] = mapped_column(String(2), nullable=False, default="")
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    parent_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("geo_areas.id", ondelete="RESTRICT"), nullable=True, index=True)
    name_uz: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    name_ru: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    name_en: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    position: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # -- django extras --
    parent: Mapped["GeoArea | None"] = relationship(foreign_keys=[parent_id], remote_side=[id], lazy="select")  # noqa: F821
    @property
    def name(self) -> str:
        by_language = {"ru": self.name_ru, "en": self.name_en}
        return by_language.get(get_language() or "", "") or self.name_uz
