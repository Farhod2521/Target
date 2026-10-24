from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, LargeBinary, Numeric, String, Text, UniqueConstraint, Uuid, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.common.db import Base, utcnow
from sqlalchemy.orm import relationship


class PageAccount(Base):
    __tablename__ = "page_accounts"
    __table_args__ = (
        UniqueConstraint('owner_id', 'provider', 'external_id', name="uniq_page_per_owner"),
        Index("uniq_current_page_per_owner", 'owner_id', 'provider', unique=True, postgresql_where=text("is_current = true")),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    owner_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False, index=True, default="")
    external_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True, default="")
    connection_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("provider_connections.id", ondelete="RESTRICT"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    token_encrypted: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    token_fingerprint: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    leadgen_subscribed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    leadgen_subscribed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    tasks: Mapped[list[Any]] = mapped_column(ARRAY(String(32)), nullable=False, default=list)
    may_advertise: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    leadgen_terms_accepted: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    location_city: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    location_city_key: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    location_lat: Mapped[Decimal | None] = mapped_column(Numeric(9, 6), nullable=True)
    location_lng: Mapped[Decimal | None] = mapped_column(Numeric(9, 6), nullable=True)
    instagram_user_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    instagram_username: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    instagram_name: Mapped[str] = mapped_column(Text, nullable=False, default="")
    instagram_biography: Mapped[str] = mapped_column(Text, nullable=False, default="")
    instagram_website: Mapped[str] = mapped_column(Text, nullable=False, default="")
    instagram_picture_url: Mapped[str] = mapped_column(Text, nullable=False, default="")
    instagram_followers: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    instagram_follows: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    instagram_posts: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    instagram_profile_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    instagram_media_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    ad_account_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("ad_accounts.id", ondelete="SET NULL"), nullable=True, index=True)
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    forms_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # -- django extras --
    owner: Mapped["User"] = relationship(foreign_keys=[owner_id], lazy="select")  # noqa: F821
    connection: Mapped["ProviderConnection"] = relationship(foreign_keys=[connection_id], lazy="select")  # noqa: F821
    ad_account: Mapped["AdAccount | None"] = relationship(foreign_keys=[ad_account_id], lazy="select")  # noqa: F821

    @property
    def has_instagram(self) -> bool:
        return bool(self.instagram_user_id)

    @property
    def can_open_profile(self) -> bool:
        return bool(self.instagram_user_id and self.instagram_username)

    @property
    def has_pin(self) -> bool:
        return self.location_lat is not None and self.location_lng is not None

    def __str__(self) -> str:
        return self.name or self.external_id
