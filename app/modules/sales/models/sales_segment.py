from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import DateTime, ForeignKey, SmallInteger, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.db import Base, utcnow


class SalesSegment(Base):
    __tablename__ = "sales_segments"
    __table_args__ = (
        UniqueConstraint('plan_id', 'days', name="uniq_sales_segment_plan_days"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    plan_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("plans.id", ondelete="CASCADE"), nullable=False, index=True)
    days: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    # -- django extras --
    plan: Mapped["Plan"] = relationship(foreign_keys=[plan_id], lazy="select")  # noqa: F821
    created_by: Mapped["User | None"] = relationship(foreign_keys=[created_by_id], lazy="select")  # noqa: F821
