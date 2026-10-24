from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, SmallInteger, String, UniqueConstraint, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.db import Base, utcnow


class ReferralReward(Base):
    __tablename__ = "referral_rewards"
    __table_args__ = (
        UniqueConstraint('binding_id', name="uniq_reward_per_binding"),
        UniqueConstraint('invoice_id', name="uniq_reward_per_invoice"),
        Index("referral_re_owner_i_d8b569_idx", 'owner_id', text("earned_at DESC")),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    owner_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    binding_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("referral_bindings.id", ondelete="SET NULL"), nullable=True, index=True)
    invoice_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("invoices.id", ondelete="SET NULL"), nullable=True, index=True)
    base_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="")
    percent: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=20)
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default='earned')
    earned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # -- django extras --
    owner: Mapped["User"] = relationship(foreign_keys=[owner_id], lazy="select")  # noqa: F821
    binding: Mapped["ReferralBinding"] = relationship(foreign_keys=[binding_id], lazy="select")  # noqa: F821
    invoice: Mapped["Invoice | None"] = relationship(foreign_keys=[invoice_id], lazy="select")  # noqa: F821
