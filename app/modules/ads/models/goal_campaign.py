from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import DateTime, ForeignKey, Index, SmallInteger, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.db import Base, utcnow


class GoalCampaign(Base):
    __tablename__ = "goal_campaigns"
    __table_args__ = (
        UniqueConstraint('owner_id', 'ad_account_id', 'page_id', 'goal', 'number', name="uniq_goal_campaign_number"),
        Index("goal_campai_owner_i_1f133d_idx", 'owner_id', 'page_id', 'goal'),
        Index("goal_campai_owner_i_48501e_idx", 'owner_id', 'external_id'),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    owner_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    ad_account_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("ad_accounts.id", ondelete="RESTRICT"), nullable=False, index=True)
    page_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("page_accounts.id", ondelete="RESTRICT"), nullable=False, index=True)
    goal: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    objective_raw: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    number: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    external_id: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    retired_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # -- django extras --
    owner: Mapped["User"] = relationship(foreign_keys=[owner_id], lazy="select")  # noqa: F821
    ad_account: Mapped["AdAccount"] = relationship(foreign_keys=[ad_account_id], lazy="select")  # noqa: F821
    page: Mapped["PageAccount"] = relationship(foreign_keys=[page_id], lazy="select")  # noqa: F821
