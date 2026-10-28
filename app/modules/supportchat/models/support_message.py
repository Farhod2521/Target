from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.db import Base, utcnow


class SupportMessage(Base):
    __tablename__ = "support_messages"
    __table_args__ = (
        Index("support_msg_thread_idx", 'owner_id', 'conversation_id', 'created_at'),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    owner_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    conversation_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("support_conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    sender_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default='text')
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    reply_to_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("support_messages.id", ondelete="SET NULL"), nullable=True, index=True)
    sticker: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attachment: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    original_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    mime: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    # -- django extras --
    owner: Mapped["User"] = relationship(foreign_keys=[owner_id], lazy="select")  # noqa: F821
    conversation: Mapped["SupportConversation"] = relationship(foreign_keys=[conversation_id], lazy="select")  # noqa: F821
    sender: Mapped["User | None"] = relationship(foreign_keys=[sender_id], lazy="select")  # noqa: F821
    reply_to: Mapped["SupportMessage | None"] = relationship(foreign_keys=[reply_to_id], remote_side=[id], lazy="select")  # noqa: F821
