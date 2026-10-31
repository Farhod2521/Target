from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, SmallInteger, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.db import Base, Json, utcnow


class LaunchCreative(Base):
    __tablename__ = "launch_creatives"
    __table_args__ = (
        UniqueConstraint('launch_id', 'position', name="uniq_variant_per_launch"),
        Index("launch_crea_launch__5a44db_idx", 'launch_id', 'position'),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    owner_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    launch_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("campaign_launches.id", ondelete="CASCADE"), nullable=False, index=True)
    position: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    group: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    ad_name: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    media_asset_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("media_assets.id", ondelete="SET NULL"), nullable=True, index=True)
    media_upload: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    library_upload: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    upload_refusal: Mapped[Any] = mapped_column(Json, nullable=False, default=dict)
    brief: Mapped[str] = mapped_column(Text, nullable=False, default="")
    primary_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    headline: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    description: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    # -- django extras --
    owner: Mapped["User"] = relationship(foreign_keys=[owner_id], lazy="select")  # noqa: F821
    launch: Mapped["CampaignLaunch"] = relationship(foreign_keys=[launch_id], lazy="select")  # noqa: F821
    media_asset: Mapped["MediaAsset | None"] = relationship(foreign_keys=[media_asset_id], lazy="select")  # noqa: F821
    @property
    def has_media(self) -> bool:
        return bool(self.media_asset_id or self.media_upload)
