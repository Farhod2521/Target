from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.db import Base, utcnow


class ContactHold(Base):
    __tablename__ = "sales_contact_holds"
    __table_args__ = (
        Index("sales_conta_owner_i_8c55fd_idx", 'owner_id', 'lifted_at'),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True, index=True)
    consult_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("consult_requests.id", ondelete="RESTRICT"), nullable=True, index=True)
    claim_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("sales_claims.id", ondelete="SET NULL"), nullable=True, index=True)
    set_by_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    reason_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("sales_lost_reasons.id", ondelete="RESTRICT"), nullable=True, index=True)
    until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lifted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lifted_by_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    lift_kind: Mapped[str] = mapped_column(String(8), nullable=False, default="")
    # -- django extras --
    owner: Mapped["User | None"] = relationship(foreign_keys=[owner_id], lazy="select")  # noqa: F821
    consult: Mapped["ConsultRequest | None"] = relationship(foreign_keys=[consult_id], lazy="select")  # noqa: F821
    claim: Mapped["SalesClaim | None"] = relationship(foreign_keys=[claim_id], lazy="select")  # noqa: F821
    set_by: Mapped["User | None"] = relationship(foreign_keys=[set_by_id], lazy="select")  # noqa: F821
    reason: Mapped["LostReason | None"] = relationship(foreign_keys=[reason_id], lazy="select")  # noqa: F821
    lifted_by: Mapped["User | None"] = relationship(foreign_keys=[lifted_by_id], lazy="select")  # noqa: F821
