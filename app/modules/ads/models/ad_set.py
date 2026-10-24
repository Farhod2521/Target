from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, String, Text, UniqueConstraint, Uuid
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.db import Base, Json, utcnow


class AdSet(Base):
    __tablename__ = "adsets"
    __table_args__ = (
        UniqueConstraint('provider', 'external_id', name="uniq_adset_per_provider"),
        Index("adsets_owner_i_94440c_idx", 'owner_id', 'delivery'),
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
    campaign_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False, index=True)
    optimization_goal_raw: Mapped[str] = mapped_column(Text, nullable=False, default="")
    billing_event_raw: Mapped[str] = mapped_column(Text, nullable=False, default="")
    destination_type_raw: Mapped[str] = mapped_column(Text, nullable=False, default="")
    daily_budget_minor: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="")
    targeting_raw: Mapped[Any] = mapped_column(Json, nullable=False, default=dict)
    promoted_object_raw: Mapped[Any] = mapped_column(Json, nullable=False, default=dict)
    learning_status: Mapped[str] = mapped_column(Text, nullable=False, default="")
    is_learning: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    start_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    end_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    issues: Mapped[Any] = mapped_column(Json, nullable=False, default=list)
    issue_codes: Mapped[list[Any]] = mapped_column(ARRAY(String(32)), nullable=False, default=list)
    issue_summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    recommendations: Mapped[Any] = mapped_column(Json, nullable=False, default=list)
    # -- django extras --
    owner: Mapped["User"] = relationship(foreign_keys=[owner_id], lazy="select")  # noqa: F821
    campaign: Mapped["Campaign"] = relationship(foreign_keys=[campaign_id], lazy="select")  # noqa: F821
    ads: Mapped[list["Ad"]] = relationship(  # noqa: F821
        "Ad", primaryjoin="Ad.adset_id == AdSet.id", viewonly=True, lazy="select"
    )
