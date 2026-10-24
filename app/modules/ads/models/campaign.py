from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, Text, UniqueConstraint, Uuid, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.db import Base, Json, utcnow


class Campaign(Base):
    __tablename__ = "campaigns"
    __table_args__ = (
        UniqueConstraint('provider', 'external_id', name="uniq_campaign_per_provider"),
        Index("campaigns_owner_i_a6419c_idx", 'owner_id', text("created_time DESC")),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    owner_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False, index=True, default="")
    external_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True, default="")
    name: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(Text, nullable=False, default="")
    effective_status: Mapped[str] = mapped_column(Text, nullable=False, default="")
    delivery: Mapped[str] = mapped_column(String(16), nullable=False, default='unknown')
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ad_account_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("ad_accounts.id", ondelete="CASCADE"), nullable=False, index=True)
    objective_raw: Mapped[str] = mapped_column(Text, nullable=False, default="")
    daily_budget_minor: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    spend_cap_minor: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    shared_budget_id: Mapped[str] = mapped_column(Text, nullable=False, default="")
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="")
    special_ad_categories: Mapped[list[Any]] = mapped_column(ARRAY(Text), nullable=False, default=list)
    created_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    issues: Mapped[Any] = mapped_column(Json, nullable=False, default=list)
    issue_codes: Mapped[list[Any]] = mapped_column(ARRAY(String(32)), nullable=False, default=list)
    issue_summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    recommendations: Mapped[Any] = mapped_column(Json, nullable=False, default=list)
    # -- django extras --
    owner: Mapped["User"] = relationship(foreign_keys=[owner_id], lazy="select")  # noqa: F821
    ad_account: Mapped["AdAccount"] = relationship(foreign_keys=[ad_account_id], lazy="select")  # noqa: F821
    adsets: Mapped[list["AdSet"]] = relationship(  # noqa: F821
        "AdSet", primaryjoin="AdSet.campaign_id == Campaign.id", viewonly=True, lazy="select"
    )
