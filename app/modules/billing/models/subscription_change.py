from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import DateTime, ForeignKey, Index, SmallInteger, String, Text, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.db import Base, utcnow


class SubscriptionChange(Base):
    __tablename__ = "subscription_changes"
    __table_args__ = (
        Index("subscriptio_owner_i_b9bbbd_idx", 'owner_id', text("occurred_at DESC")),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    owner_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    subscription_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("subscriptions.id", ondelete="RESTRICT"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    move: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    from_plan_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("plans.id", ondelete="RESTRICT"), nullable=True, index=True)
    to_plan_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("plans.id", ondelete="RESTRICT"), nullable=False, index=True)
    days: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    expires_before: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    invoice_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("invoices.id", ondelete="RESTRICT"), nullable=True, index=True)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # -- django extras --
    owner: Mapped["User"] = relationship(foreign_keys=[owner_id], lazy="select")  # noqa: F821
    subscription: Mapped["Subscription"] = relationship(foreign_keys=[subscription_id], lazy="select")  # noqa: F821
    from_plan: Mapped["Plan | None"] = relationship(foreign_keys=[from_plan_id], lazy="select")  # noqa: F821
    to_plan: Mapped["Plan | None"] = relationship(foreign_keys=[to_plan_id], lazy="select")  # noqa: F821
    invoice: Mapped["Invoice | None"] = relationship(foreign_keys=[invoice_id], lazy="select")  # noqa: F821
    actor: Mapped["User | None"] = relationship(foreign_keys=[actor_id], lazy="select")  # noqa: F821
    @property
    def days_back(self) -> int:
        return -self.days
