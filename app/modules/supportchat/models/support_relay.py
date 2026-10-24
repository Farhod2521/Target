from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.db import Base, utcnow


class SupportRelay(Base):
    __tablename__ = "support_relays"
    __table_args__ = (
        UniqueConstraint('bot', 'chat_id', 'telegram_message_id', name="uniq_support_relay_per_bot_message"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    owner_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    message_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("support_messages.id", ondelete="CASCADE"), nullable=False, index=True)
    bot: Mapped[str] = mapped_column(String(16), nullable=False, default='customer')
    chat_id: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    telegram_message_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    answered_by_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    # -- django extras --
    owner: Mapped["User"] = relationship(foreign_keys=[owner_id], lazy="select")  # noqa: F821
    message: Mapped["SupportMessage"] = relationship(foreign_keys=[message_id], lazy="select")  # noqa: F821
    answered_by: Mapped["User | None"] = relationship(foreign_keys=[answered_by_id], lazy="select")  # noqa: F821
