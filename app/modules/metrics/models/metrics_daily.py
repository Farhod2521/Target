from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import BigInteger, Date, DateTime, ForeignKey, Index, Numeric, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.db import Base, utcnow


class MetricsDaily(Base):
    __tablename__ = "metrics_daily"
    __table_args__ = (
        UniqueConstraint('owner_id', 'provider', 'level', 'external_id', 'date', name="uniq_metrics_per_object_per_day"),
        Index("metrics_owner_date", 'owner_id', 'date'),
        Index("metrics_owner_adset_date", 'owner_id', 'adset_external_id', 'date'),
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    owner_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False, index=True, default="")
    external_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True, default="")
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ad_account_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("ad_accounts.id", ondelete="CASCADE"), nullable=True, index=True)
    level: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    campaign_external_id: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    adset_external_id: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    ad_external_id: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    date: Mapped[date] = mapped_column(Date, nullable=False)
    spend_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="")
    impressions: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    reach: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    clicks: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    leads_reported: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    results_reported: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    recallers: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    profile_visits: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    frequency: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False, default=0)
    ctr: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False, default=0)
    cpm_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    cpc_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    object_name: Mapped[str] = mapped_column(Text, nullable=False, default="")
    unique_clicks: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    inline_link_clicks: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    unique_inline_link_clicks: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    outbound_clicks: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    landing_page_views: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    video_plays: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    video_thruplays: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    video_p25: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    video_p50: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    video_p75: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    video_p100: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    video_views_3s: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    reactions: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    comments: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    shares: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    saves: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    cost_per_lead_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    lead_value_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    quality_ranking: Mapped[str] = mapped_column(String(24), nullable=False, default="")
    engagement_rate_ranking: Mapped[str] = mapped_column(String(24), nullable=False, default="")
    conversion_rate_ranking: Mapped[str] = mapped_column(String(24), nullable=False, default="")
    attribution_setting: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # -- django extras --
    owner: Mapped["User"] = relationship(foreign_keys=[owner_id], lazy="select")  # noqa: F821
    ad_account: Mapped["AdAccount | None"] = relationship(foreign_keys=[ad_account_id], lazy="select")  # noqa: F821
