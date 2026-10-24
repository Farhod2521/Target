from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.db import Base, Json, utcnow


class AdCreative(Base):
    __tablename__ = "ad_creatives"
    __table_args__ = (
        UniqueConstraint('provider', 'external_id', name="uniq_creative_per_provider"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    owner_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False, index=True, default="")
    external_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True, default="")
    ad_account_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("ad_accounts.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(Text, nullable=False, default="")
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    headline: Mapped[str] = mapped_column(Text, nullable=False, default="")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    link_url: Mapped[str] = mapped_column(Text, nullable=False, default="")
    call_to_action: Mapped[str] = mapped_column(Text, nullable=False, default="")
    image_hash: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    video_id: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    thumbnail_url: Mapped[str] = mapped_column(Text, nullable=False, default="")
    page_id: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    instagram_user_id: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    post_external_id: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    story_raw: Mapped[Any] = mapped_column(Json, nullable=False, default=dict)
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # -- django extras --
    owner: Mapped["User"] = relationship(foreign_keys=[owner_id], lazy="select")  # noqa: F821
    ad_account: Mapped["AdAccount"] = relationship(foreign_keys=[ad_account_id], lazy="select")  # noqa: F821
