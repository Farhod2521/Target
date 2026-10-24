from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.db import Base, utcnow


class SalesActivity(Base):
    __tablename__ = "sales_activities"
    __table_args__ = (
        Index("sales_activ_owner_i_22e32b_idx", 'owner_id', text("created_at DESC")),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    owner_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=True, index=True)
    consult_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("consult_requests.id", ondelete="RESTRICT"), nullable=True, index=True)
    claim_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("sales_claims.id", ondelete="CASCADE"), nullable=False, index=True)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    reason_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("sales_lost_reasons.id", ondelete="RESTRICT"), nullable=True, index=True)
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    callback_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # -- django extras --
    owner: Mapped["User | None"] = relationship(foreign_keys=[owner_id], lazy="select")  # noqa: F821
    consult: Mapped["ConsultRequest | None"] = relationship(foreign_keys=[consult_id], lazy="select")  # noqa: F821
    claim: Mapped["SalesClaim"] = relationship(foreign_keys=[claim_id], lazy="select")  # noqa: F821
    actor: Mapped["User | None"] = relationship(foreign_keys=[actor_id], lazy="select")  # noqa: F821
    reason: Mapped["LostReason | None"] = relationship(foreign_keys=[reason_id], lazy="select")  # noqa: F821
