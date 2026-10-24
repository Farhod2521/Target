from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.db import Base, Json, utcnow


class BrandKit(Base):
    __tablename__ = "montage_brand_kits"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    owner_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    page_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("page_accounts.id", ondelete="CASCADE"), nullable=False, unique=True)
    brand_name: Mapped[str] = mapped_column(String(60), nullable=False, default="")
    description: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    tagline: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    logo: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    logo_trimmed: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    logo_on_dark: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    logo_on_light: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    logo_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    logo_colors: Mapped[Any] = mapped_column(Json, nullable=False, default=list)
    logo_color: Mapped[str] = mapped_column(String(7), nullable=False, default="")
    logo_has_alpha: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    logo_aspect: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    logo_ground: Mapped[str] = mapped_column(String(16), nullable=False, default='clear')
    logo_analysis: Mapped[Any] = mapped_column(Json, nullable=False, default=dict)
    logo_analysis_status: Mapped[str] = mapped_column(String(16), nullable=False, default='none')
    logo_analysis_version: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    logo_analyzed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    failure_detail: Mapped[str] = mapped_column(Text, nullable=False, default="")
    primary_color: Mapped[str] = mapped_column(String(7), nullable=False, default="")
    accent_color: Mapped[str] = mapped_column(String(7), nullable=False, default="")
    text_color: Mapped[str] = mapped_column(String(7), nullable=False, default="")
    font_preset: Mapped[str] = mapped_column(String(16), nullable=False, default='modern')
    cta_telegram: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    cta_instagram: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    cta_phone: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    cta_text: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    keyterms: Mapped[Any] = mapped_column(Json, nullable=False, default=list)
    show_corner_logo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    video_language: Mapped[str] = mapped_column(String(2), nullable=False, default='uz')
    brand_brief: Mapped[str] = mapped_column(Text, nullable=False, default="")
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # -- django extras --
    owner: Mapped["User"] = relationship(foreign_keys=[owner_id], lazy="select")  # noqa: F821
    page: Mapped["PageAccount"] = relationship(foreign_keys=[page_id], lazy="select")  # noqa: F821
