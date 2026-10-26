from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.db import Base, utcnow


class DeliveryStop(Base):
    __tablename__ = "delivery_stops"
    __table_args__ = (
        Index("uniq_open_delivery_stop", 'owner_id', 'level', 'external_id', 'reason', unique=True, postgresql_where=text("cleared_at IS NULL")),
        Index("delivery_st_owner_i_5e0c1b_idx", 'owner_id', 'cleared_at'),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    owner_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    ad_account_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("ad_accounts.id", ondelete="CASCADE"), nullable=False, index=True)
    level: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    external_id: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    name: Mapped[str] = mapped_column(Text, nullable=False, default="")
    campaign_external_id: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    reason: Mapped[str] = mapped_column(String(24), nullable=False, default="")
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    cleared_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # -- django extras --
    owner: Mapped["User"] = relationship(foreign_keys=[owner_id], lazy="select")  # noqa: F821
    ad_account: Mapped["AdAccount"] = relationship(foreign_keys=[ad_account_id], lazy="select")  # noqa: F821
