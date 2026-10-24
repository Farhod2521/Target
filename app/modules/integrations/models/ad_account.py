from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, String, UniqueConstraint, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column

from app.common.db import Base, utcnow
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from sqlalchemy.orm import relationship


class AdAccount(Base):
    __tablename__ = "ad_accounts"
    __table_args__ = (
        UniqueConstraint('provider', 'external_id', name="uniq_ad_account_per_provider"),
        Index("uniq_current_ad_account_per_owner", 'owner_id', 'provider', unique=True, postgresql_where=text("is_current = true")),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    owner_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False, index=True, default="")
    external_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True, default="")
    connection_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("provider_connections.id", ondelete="RESTRICT"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    business_external_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="")
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    account_status: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    disable_reason: Mapped[str] = mapped_column(String(8), nullable=False, default="")
    may_advertise: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    payment_due: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    min_daily_budget_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    spend_cap_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    amount_spent_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    custom_audience_terms_accepted: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_current: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    leads_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    media_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # -- django extras --
    owner: Mapped["User"] = relationship(foreign_keys=[owner_id], lazy="select")  # noqa: F821
    connection: Mapped["ProviderConnection"] = relationship(foreign_keys=[connection_id], lazy="select")  # noqa: F821

    def tzinfo(self) -> ZoneInfo:
        try:
            return ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError):
            return ZoneInfo("UTC")

    @property
    def cap_reached(self) -> bool:
        return bool(self.spend_cap_minor) and (self.amount_spent_minor >= self.spend_cap_minor)

    def __str__(self) -> str:
        return self.name or self.external_id
