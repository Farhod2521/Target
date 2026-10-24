from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, SmallInteger, String, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.db import Base, utcnow


class SalesCommission(Base):
    __tablename__ = "sales_commissions"
    __table_args__ = (
        Index("sales_commi_owner_i_d5d67d_idx", 'owner_id', text("earned_at DESC")),
        Index("sales_commi_earned__f574fc_idx", 'earned_at'),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    owner_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    client_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    invoice_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("invoices.id", ondelete="SET NULL"), nullable=True, unique=True)
    claim_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("sales_claims.id", ondelete="SET NULL"), nullable=True, index=True)
    base_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    percent: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    amount_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="")
    earned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # -- django extras --
    owner: Mapped["User"] = relationship(foreign_keys=[owner_id], lazy="select")  # noqa: F821
    client: Mapped["User | None"] = relationship(foreign_keys=[client_id], lazy="select")  # noqa: F821
    invoice: Mapped["Invoice | None"] = relationship(foreign_keys=[invoice_id], lazy="select")  # noqa: F821
    claim: Mapped["SalesClaim | None"] = relationship(foreign_keys=[claim_id], lazy="select")  # noqa: F821
