from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, Index, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.db import Base, utcnow


class PeopleCount(Base):
    __tablename__ = "metrics_people_count"
    __table_args__ = (
        UniqueConstraint('ad_account_id', 'level', 'external_id', 'since', 'until', name="uniq_people_per_object_per_range"),
        Index("mpeople_owner_level_range", 'owner_id', 'level', 'since', 'until'),
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    owner_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False, index=True, default="")
    external_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True, default="")
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ad_account_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("ad_accounts.id", ondelete="CASCADE"), nullable=False, index=True)
    level: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    campaign_external_id: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    adset_external_id: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    ad_external_id: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    since: Mapped[date] = mapped_column(Date, nullable=False)
    until: Mapped[date] = mapped_column(Date, nullable=False)
    reach: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    recallers: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # -- django extras --
    owner: Mapped["User"] = relationship(foreign_keys=[owner_id], lazy="select")  # noqa: F821
    ad_account: Mapped["AdAccount"] = relationship(foreign_keys=[ad_account_id], lazy="select")  # noqa: F821
