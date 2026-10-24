from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, SmallInteger, String, Text, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.db import Base, utcnow


class Testimonial(Base):
    __tablename__ = "testimonials"
    __table_args__ = (
        CheckConstraint(text("(NOT (image = '')) OR (NOT (video = '')) OR (NOT (audio = '')) OR (NOT (text = ''))"), name="testimonial_has_something_to_show"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    image: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    video: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    audio: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    source_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("feedback.id", ondelete="CASCADE"), nullable=True, unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    # -- django extras --
    source: Mapped["Feedback | None"] = relationship(foreign_keys=[source_id], lazy="select")  # noqa: F821
    @property
    def kind(self) -> str:
        if self.video:
            return "video"
        if self.audio:
            return "audio"
        if self.text:
            return "text"
        return "image"

    @property
    def is_video(self) -> bool:
        return bool(self.video)
