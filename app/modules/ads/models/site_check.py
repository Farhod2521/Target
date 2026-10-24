from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.db import Base, Json, utcnow


class SiteCheck(Base):
    __tablename__ = "site_checks"
    __table_args__ = (
        UniqueConstraint('owner_id', 'url_digest', name="uniq_site_check_per_owner"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    owner_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    url: Mapped[str] = mapped_column(Text, nullable=False, default="")
    url_digest: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    final_url: Mapped[str] = mapped_column(Text, nullable=False, default="")
    outcome: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    status_code: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    meta_pixel_ids: Mapped[Any] = mapped_column(Json, nullable=False, default=list)
    has_tag_manager: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_down: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    down_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # -- django extras --
    owner: Mapped["User"] = relationship(foreign_keys=[owner_id], lazy="select")  # noqa: F821
