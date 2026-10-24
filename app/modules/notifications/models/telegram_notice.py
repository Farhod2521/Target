from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, SmallInteger, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.db import Base, utcnow


class TelegramNotice(Base):
    __tablename__ = "telegram_notices"
    __table_args__ = (
        UniqueConstraint('owner_id', 'kind', 'subject', name="uniq_telegram_notice_per_subject"),
        Index("tg_notice_owner_kind", 'owner_id', 'kind'),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    owner_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    chat_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("telegram_chats.id", ondelete="RESTRICT"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    subject: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    message_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attempts: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    # -- django extras --
    owner: Mapped["User"] = relationship(foreign_keys=[owner_id], lazy="select")  # noqa: F821
    chat: Mapped["TelegramChat"] = relationship(foreign_keys=[chat_id], lazy="select")  # noqa: F821
