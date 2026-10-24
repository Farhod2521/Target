from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, SmallInteger, String, Text, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.db import Base, utcnow


class PromoRedemption(Base):
    __tablename__ = "promo_redemptions"
    __table_args__ = (
        Index("promo_redem_promo_i_d15c48_idx", 'promo_id', 'owner_id'),
        Index("promo_redem_status_16de40_idx", 'status', text("redeemed_at DESC")),
        Index("idx_promo_unannounced", 'owner_id', text("redeemed_at DESC")),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    owner_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    promo_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("promo_codes.id", ondelete="RESTRICT"), nullable=False, index=True)
    subscription_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("subscriptions.id", ondelete="RESTRICT"), nullable=True, index=True)
    invoice_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("invoices.id", ondelete="RESTRICT"), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default='approved')
    decided_by_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decision_note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    granted_days: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    granted_pages: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    discount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    redeemed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    acknowledged_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # -- django extras --
    owner: Mapped["User"] = relationship(foreign_keys=[owner_id], lazy="select")  # noqa: F821
    decided_by: Mapped["User | None"] = relationship(foreign_keys=[decided_by_id], lazy="select")  # noqa: F821
    promo: Mapped["PromoCode"] = relationship(foreign_keys=[promo_id], lazy="select")  # noqa: F821
    invoice: Mapped["Invoice | None"] = relationship(foreign_keys=[invoice_id], lazy="select")  # noqa: F821
    subscription: Mapped["Subscription | None"] = relationship(foreign_keys=[subscription_id], lazy="select")  # noqa: F821
