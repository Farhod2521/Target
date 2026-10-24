from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, UniqueConstraint, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column

from app.common.db import Base, Json, utcnow
from sqlalchemy.orm import relationship


class PixelAccount(Base):
    __tablename__ = "pixel_accounts"
    __table_args__ = (
        UniqueConstraint('owner_id', 'provider', 'ad_account_id', 'external_id', name="uniq_pixel_per_account"),
        Index("uniq_active_pixel_per_account", 'owner_id', 'provider', 'ad_account_id', unique=True, postgresql_where=text("is_active = true")),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    owner_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False, index=True, default="")
    external_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True, default="")
    connection_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("provider_connections.id", ondelete="RESTRICT"), nullable=False, index=True)
    ad_account_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("ad_accounts.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    is_unavailable: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_fired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    recent_events: Mapped[Any] = mapped_column(Json, nullable=False, default=list)
    events_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # -- django extras --
    owner: Mapped["User"] = relationship(foreign_keys=[owner_id], lazy="select")  # noqa: F821
    connection: Mapped["ProviderConnection"] = relationship(foreign_keys=[connection_id], lazy="select")  # noqa: F821
    ad_account: Mapped["AdAccount"] = relationship(foreign_keys=[ad_account_id], lazy="select")  # noqa: F821

    def __str__(self) -> str:
        return self.name or self.external_id
