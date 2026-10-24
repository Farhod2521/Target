from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.db import Base, utcnow


class MediaAsset(Base):
    __tablename__ = "media_assets"
    __table_args__ = (
        UniqueConstraint('owner_id', 'provider', 'kind', 'external_id', name="uniq_media_asset_per_owner"),
        Index("media_asset_owner_i_d8a3c9_idx", 'owner_id', 'provider', 'kind'),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    owner_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    ad_account_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("ad_accounts.id", ondelete="CASCADE"), nullable=True, index=True)
    page_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("page_accounts.id", ondelete="CASCADE"), nullable=True, index=True)
    instagram_user_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    provider: Mapped[str] = mapped_column(String(32), nullable=False, index=True, default="")
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    external_id: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    name: Mapped[str] = mapped_column(Text, nullable=False, default="")
    thumbnail_url: Mapped[str] = mapped_column(Text, nullable=False, default="")
    permalink_url: Mapped[str] = mapped_column(Text, nullable=False, default="")
    width: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    height: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_eligible: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    ineligible_reason: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    created_at_provider: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # -- django extras --
    owner: Mapped["User"] = relationship(foreign_keys=[owner_id], lazy="select")  # noqa: F821
    ad_account: Mapped["AdAccount | None"] = relationship(foreign_keys=[ad_account_id], lazy="select")  # noqa: F821
    page: Mapped["PageAccount | None"] = relationship(foreign_keys=[page_id], lazy="select")  # noqa: F821
    @property
    def is_instagram(self) -> bool:
        from app.modules.ads.constants import IG_KINDS

        return self.kind in IG_KINDS

    @property
    def is_video(self) -> bool:
        from app.modules.ads.constants import MediaKind

        return self.kind in (MediaKind.VIDEO, MediaKind.IG_VIDEO)

    @property
    def is_blocked(self) -> bool:
        return self.is_eligible is False

    @property
    def is_too_small(self) -> bool:
        from app.modules.ads.constants import MIN_IMAGE_SIDE

        if not self.width or not self.height:
            return False
        return min(self.width, self.height) < MIN_IMAGE_SIDE
