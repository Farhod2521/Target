from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, Date, DateTime, ForeignKey, Index, SmallInteger, String, Text, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.db import Base, Json, utcnow


class CampaignLaunch(Base):
    __tablename__ = "campaign_launches"
    __table_args__ = (
        Index("campaign_la_owner_i_4386a9_idx", 'owner_id', 'status'),
        Index("campaign_la_owner_i_831f37_idx", 'owner_id', text("created_at DESC")),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    owner_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False, index=True, default="")
    ad_account_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("ad_accounts.id", ondelete="RESTRICT"), nullable=False, index=True)
    page_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("page_accounts.id", ondelete="RESTRICT"), nullable=True, index=True)
    answers: Mapped[Any] = mapped_column(Json, nullable=False, default=dict)
    draft: Mapped[Any] = mapped_column(Json, nullable=False, default=dict)
    preset_key: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    preset_version: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    targeting: Mapped[Any] = mapped_column(Json, nullable=False, default=dict)
    daily_budget_minor: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    ad_groups: Mapped[Any] = mapped_column(Json, nullable=False, default=list)
    campaign_name: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    max_result_cost_minor: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="")
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    total_cap_minor: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    daily_min_minor: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    daily_max_minor: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    audience_lower: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    audience_upper: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    estimated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default='draft')
    step: Mapped[str] = mapped_column(String(24), nullable=False, default="")
    progress: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    created_refs: Mapped[Any] = mapped_column(Json, nullable=False, default=dict)
    goal_campaign_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("goal_campaigns.id", ondelete="RESTRICT"), nullable=True, index=True)
    lead_form_external_id: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    buy_qualified_leads: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    dropped: Mapped[Any] = mapped_column(Json, nullable=False, default=dict)
    celery_task_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    error_code: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    error_message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    error_detail: Mapped[Any] = mapped_column(Json, nullable=False, default=dict)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivery_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivery_note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # -- django extras --
    owner: Mapped["User"] = relationship(foreign_keys=[owner_id], lazy="select")  # noqa: F821
    ad_account: Mapped["AdAccount"] = relationship(foreign_keys=[ad_account_id], lazy="select")  # noqa: F821
    page: Mapped["PageAccount | None"] = relationship(foreign_keys=[page_id], lazy="select")  # noqa: F821
    goal_campaign: Mapped["GoalCampaign | None"] = relationship(foreign_keys=[goal_campaign_id], lazy="select")  # noqa: F821
    variants: Mapped[list["LaunchCreative"]] = relationship(  # noqa: F821
        "LaunchCreative",
        primaryjoin="LaunchCreative.launch_id == CampaignLaunch.id",
        order_by="LaunchCreative.position",
        viewonly=True,
        lazy="select",
    )
