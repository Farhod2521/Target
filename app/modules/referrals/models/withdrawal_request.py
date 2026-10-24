from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, LargeBinary, String, Text, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.db import Base, utcnow


class WithdrawalRequest(Base):
    __tablename__ = "withdrawal_requests"
    __table_args__ = (
        Index("uniq_open_withdrawal_per_owner", 'owner_id', unique=True, postgresql_where=text("status = 'requested'")),
        Index("withdrawal__owner_i_f01d8d_idx", 'owner_id', text("created_at DESC")),
        Index("withdrawal__status_e67567_idx", 'status', text("created_at DESC")),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    owner_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="")
    method: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    pay_reference: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default='paid')
    decided_by_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    card_number_encrypted: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    card_last4: Mapped[str] = mapped_column(String(4), nullable=False, default="")
    card_holder: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    reject_reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    void_reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    voided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    voided_by_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    # -- django extras --
    voided_by: Mapped["User | None"] = relationship(foreign_keys=[voided_by_id], lazy="select")  # noqa: F821
    owner: Mapped["User"] = relationship(foreign_keys=[owner_id], lazy="select")  # noqa: F821
    decided_by: Mapped["User | None"] = relationship(foreign_keys=[decided_by_id], lazy="select")  # noqa: F821
