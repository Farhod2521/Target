from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import BigInteger, Boolean, DateTime, SmallInteger, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.db import Base, utcnow


class Plan(Base):
    __tablename__ = "plans"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    code: Mapped[str] = mapped_column(String(32), nullable=False, unique=True, default="")
    name: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    tagline: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    features: Mapped[str] = mapped_column(Text, nullable=False, default="")
    price: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="")
    period_days: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=30)
    max_adsets: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    daily_chat_requests: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=20)
    llm_cost_limit_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    included_pages: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    included_google_accounts: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    extra_page_price: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    crm_seat_price: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    crm_free_seats: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    is_one_time: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sort_order: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    feature_rows: Mapped[list["PlanFeature"]] = relationship(  # noqa: F821
        back_populates="plan",
        order_by="(PlanFeature.sort_order, PlanFeature.id)",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="select",
    )
