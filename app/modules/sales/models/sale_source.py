from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import DateTime, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.db import Base, utcnow


class SaleSource(Base):
    __tablename__ = "sales_sources"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    owner_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    invoice_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("invoices.id", ondelete="CASCADE"), nullable=False, unique=True)
    source: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    manager_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    claim_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("sales_claims.id", ondelete="SET NULL"), nullable=True, index=True)
    paid_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    # -- django extras --
    owner: Mapped["User"] = relationship(foreign_keys=[owner_id], lazy="select")  # noqa: F821
    invoice: Mapped["Invoice"] = relationship(foreign_keys=[invoice_id], lazy="select")  # noqa: F821
    manager: Mapped["User | None"] = relationship(foreign_keys=[manager_id], lazy="select")  # noqa: F821
    claim: Mapped["SalesClaim | None"] = relationship(foreign_keys=[claim_id], lazy="select")  # noqa: F821
