from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, SmallInteger, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.db import Base, utcnow


class PromoCode(Base):
    __tablename__ = "promo_codes"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    code: Mapped[str] = mapped_column(String(32), nullable=False, unique=True, default="")
    description: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default='plan')
    needs_approval: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    grant_days: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    grant_pages: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    plan_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("plans.id", ondelete="RESTRICT"), nullable=True, index=True)
    discount_kind: Mapped[str] = mapped_column(String(16), nullable=False, default='none')
    discount_value: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    scope: Mapped[str] = mapped_column(String(16), nullable=False, default='both')
    min_amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    starts_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    max_uses: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    max_uses_per_user: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # -- django extras --
    plan: Mapped["Plan | None"] = relationship(foreign_keys=[plan_id], lazy="select")  # noqa: F821
    @property
    def grants_anything(self) -> bool:
        if self.kind == "discount":
            return False
        return bool(self.grant_days or self.grant_pages or self.plan_id is not None)


def normalise(code: str) -> str:
    return code.strip().upper()
