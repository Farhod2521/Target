from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, SmallInteger, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.db import Base, utcnow


class PlanFeature(Base):
    __tablename__ = "plan_features"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    plan_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("plans.id", ondelete="CASCADE"), nullable=False, index=True)
    text_uz: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    text_ru: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    text_en: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default='included')
    limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_highlighted: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sort_order: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    plan: Mapped["Plan"] = relationship(back_populates="feature_rows", foreign_keys=[plan_id], lazy="select")  # noqa: F821
