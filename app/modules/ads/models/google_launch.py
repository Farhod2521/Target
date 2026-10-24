from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.db import Base, Json, utcnow


class GoogleLaunch(Base):
    __tablename__ = "ads_google_launches"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    owner_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    ad_account_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("ad_accounts.id", ondelete="RESTRICT"), nullable=False, index=True)
    goal: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(16), nullable=False, index=True, default='draft')
    final_url: Mapped[str] = mapped_column(String(1000), nullable=False, default="")
    phone: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    places: Mapped[Any] = mapped_column(Json, nullable=False, default=list)
    daily_budget_minor: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="")
    keywords: Mapped[Any] = mapped_column(Json, nullable=False, default=list)
    negative_keywords: Mapped[Any] = mapped_column(Json, nullable=False, default=list)
    headlines: Mapped[Any] = mapped_column(Json, nullable=False, default=list)
    descriptions: Mapped[Any] = mapped_column(Json, nullable=False, default=list)
    path1: Mapped[str] = mapped_column(String(15), nullable=False, default="")
    path2: Mapped[str] = mapped_column(String(15), nullable=False, default="")
    volumes: Mapped[Any] = mapped_column(Json, nullable=False, default=dict)
    campaign_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    ai_written_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_refs: Mapped[Any] = mapped_column(Json, nullable=False, default=dict)
    dry_run: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    error_code: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    error_message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # -- django extras --
    owner: Mapped["User"] = relationship(foreign_keys=[owner_id], lazy="select")  # noqa: F821
    ad_account: Mapped["AdAccount"] = relationship(foreign_keys=[ad_account_id], lazy="select")  # noqa: F821
