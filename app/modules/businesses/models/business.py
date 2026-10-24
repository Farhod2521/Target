from __future__ import annotations

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Numeric, SmallInteger, String, Text, Uuid, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.common.db import Base, Json, utcnow
from sqlalchemy.orm import relationship


class Business(Base):
    __tablename__ = "businesses"
    __table_args__ = (
        CheckConstraint(text("NOT (timezone = '')"), name="business_has_a_timezone"),
        Index("uniq_pageless_business_per_user", 'user_id', unique=True, postgresql_where=text("(ad_account_id IS NULL) AND (page_id IS NULL)")),
        CheckConstraint(text("(page_id IS NULL) OR (ad_account_id IS NULL)"), name="business_page_or_google_account"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    page_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("page_accounts.id", ondelete="CASCADE"), nullable=True, unique=True)
    ad_account_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("ad_accounts.id", ondelete="CASCADE"), nullable=True, unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    category: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    direction_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("business_categories.id", ondelete="RESTRICT"), nullable=True, index=True)
    custom_category_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("business_custom_categories.id", ondelete="SET NULL"), nullable=True, index=True)
    timezone: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    country_code: Mapped[str] = mapped_column(String(2), nullable=False, default="")
    city: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    lat: Mapped[Decimal | None] = mapped_column(Numeric(9, 6), nullable=True)
    lng: Mapped[Decimal | None] = mapped_column(Numeric(9, 6), nullable=True)
    contact_phone: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    website: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    offer_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    working_hours: Mapped[Any] = mapped_column(Json, nullable=False, default=dict)
    locales: Mapped[list[Any]] = mapped_column(ARRAY(SmallInteger), nullable=False, default=list)
    special_ad_category: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    # -- django extras --
    user: Mapped["User"] = relationship(foreign_keys=[user_id], lazy="select")  # noqa: F821
    ad_account: Mapped["AdAccount | None"] = relationship(foreign_keys=[ad_account_id], lazy="select")  # noqa: F821
    direction: Mapped["BusinessCategory | None"] = relationship(foreign_keys=[direction_id], lazy="select")  # noqa: F821
    custom_category: Mapped["CustomCategory | None"] = relationship(foreign_keys=[custom_category_id], lazy="select")  # noqa: F821
    page: Mapped["PageAccount | None"] = relationship(foreign_keys=[page_id], lazy="select")  # noqa: F821

    def __str__(self) -> str:
        return self.name
