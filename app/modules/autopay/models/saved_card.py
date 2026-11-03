from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    LargeBinary,
    SmallInteger,
    String,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.db import Base, utcnow


class SavedCard(Base):
    """A payer's card at Multicard: its token, never its number."""

    __tablename__ = "saved_cards"
    __table_args__ = (
        Index(
            "uniq_active_card_per_owner",
            "owner_id",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
        Index("saved_cards_status_autopay_idx", "status", "autopay"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    owner_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False, default="multicard")
    # Multicard's binding page; its callback names the card by it.
    session_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    token_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    token_fingerprint: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    pan: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    ps: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    holder: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    autopay: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    consented_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    bound_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # The term being renewed: the plan's expiry the attempts below are for.
    charge_term: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    charge_attempts: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    last_charge_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_charge_uuid: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    last_charge_outcome: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    last_charge_error: Mapped[str] = mapped_column(String(300), nullable=False, default="")

    owner: Mapped["User"] = relationship(foreign_keys=[owner_id], lazy="select")  # noqa: F821
