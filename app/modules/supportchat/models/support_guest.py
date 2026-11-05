from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.db import Base, utcnow


class SupportGuestChat(Base):
    """A chat from somebody not signed in - the sign-in page's "Yordam".

    Kept apart from ``support_conversations``, which belong to an account.
    Whoever holds the token is the guest; signing in moves the words into
    that account's chat (``claimed_by``) and this one stops taking more.
    """

    __tablename__ = "support_guest_chats"
    __table_args__ = (
        Index("support_guest_queue_idx", text("last_message_at DESC")),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    phone: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    email: Mapped[str] = mapped_column(String(254), nullable=False, default="", index=True)
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_guest_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_office_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    guest_read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    office_read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    settled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    claimed_by_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    claimed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    claimed_by: Mapped["User | None"] = relationship(foreign_keys=[claimed_by_id], lazy="select")  # noqa: F821


class SupportGuestMessage(Base):
    """Words only, both ways: a guest sends no files."""

    __tablename__ = "support_guest_messages"
    __table_args__ = (
        Index("support_guest_msg_thread_idx", "chat_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    chat_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("support_guest_chats.id", ondelete="CASCADE"), nullable=False)
    # The guest's own words, or the office's - whose author may be erased later.
    from_guest: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    sender_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    chat: Mapped["SupportGuestChat"] = relationship(foreign_keys=[chat_id], lazy="select")  # noqa: F821
    sender: Mapped["User | None"] = relationship(foreign_keys=[sender_id], lazy="select")  # noqa: F821
