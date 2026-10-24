from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, SmallInteger, String, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.db import Base, utcnow


class SalesClaim(Base):
    __tablename__ = "sales_claims"
    __table_args__ = (
        Index("uniq_sales_claim_open", 'owner_id', unique=True, postgresql_where=text("closed_at IS NULL")),
        Index("uniq_sales_claim_open_consult", 'consult_id', unique=True, postgresql_where=text("(closed_at IS NULL) AND (owner_id IS NULL)")),
        CheckConstraint(text("(owner_id IS NOT NULL) OR (consult_id IS NOT NULL)"), name="sales_claim_has_customer"),
        Index("sales_claim_manager_50485d_idx", 'manager_id', 'closed_at'),
        Index("sales_claim_owner_i_c387d3_idx", 'owner_id', text("claimed_at DESC")),
        Index("sales_claim_closed__cd38cd_idx", 'closed_at'),
        Index("sales_claim_open_expiry_idx", 'expires_at'),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True, index=True)
    consult_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("consult_requests.id", ondelete="RESTRICT"), nullable=True, index=True)
    manager_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    group: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    stage: Mapped[str] = mapped_column(String(16), nullable=False, default='taken')
    outcome: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    attempts: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    callback_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    reason_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("sales_lost_reasons.id", ondelete="RESTRICT"), nullable=True, index=True)
    claimed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    extended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    contacted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    invoice_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("invoices.id", ondelete="SET NULL"), nullable=True, index=True)
    # -- django extras --
    owner: Mapped["User | None"] = relationship(foreign_keys=[owner_id], lazy="select")  # noqa: F821
    consult: Mapped["ConsultRequest | None"] = relationship(foreign_keys=[consult_id], lazy="select")  # noqa: F821
    manager: Mapped["User | None"] = relationship(foreign_keys=[manager_id], lazy="select")  # noqa: F821
    reason: Mapped["LostReason | None"] = relationship(foreign_keys=[reason_id], lazy="select")  # noqa: F821
    invoice: Mapped["Invoice | None"] = relationship(foreign_keys=[invoice_id], lazy="select")  # noqa: F821
    @property
    def is_open(self) -> bool:
        return self.closed_at is None

    @property
    def subject_id(self) -> uuid.UUID:
        return self.owner_id or self.consult_id  # type: ignore[return-value]
