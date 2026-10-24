from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, SmallInteger, String, Text, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.db import Base, utcnow


class Invoice(Base):
    __tablename__ = "invoices"
    __table_args__ = (
        Index("invoices_owner_i_8b688b_idx", 'owner_id', text("created_at DESC")),
        Index("invoices_status_4792b1_idx", 'status', 'expires_at'),
        Index("invoices_owner_i_793e56_idx", 'owner_id', 'pages_until'),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True, index=True)
    former_email: Mapped[str] = mapped_column(String(254), nullable=False, index=True, default="")
    number: Mapped[str] = mapped_column(String(16), nullable=False, unique=True, default="")
    plan_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("plans.id", ondelete="RESTRICT"), nullable=False, index=True)
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="")
    period_days: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default='pending')
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    canceled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    subscription_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("subscriptions.id", ondelete="RESTRICT"), nullable=True, index=True)
    applied_days: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    credit_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    wallet_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    kind: Mapped[str] = mapped_column(String(8), nullable=False, default='plan')
    pages: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    pages_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    pages_from: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    pages_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    manual_method: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    pay_reference: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    recorded_by_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # -- django extras --
    recorded_by: Mapped["User | None"] = relationship(foreign_keys=[recorded_by_id], lazy="select")  # noqa: F821
    plan: Mapped["Plan"] = relationship(foreign_keys=[plan_id], lazy="select")  # noqa: F821
    owner: Mapped["User | None"] = relationship(foreign_keys=[owner_id], lazy="select")  # noqa: F821
    subscription: Mapped["Subscription | None"] = relationship(foreign_keys=[subscription_id], lazy="select")  # noqa: F821
