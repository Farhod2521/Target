from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.db import Base, utcnow


class SupportBotChat(Base):
    """One Telegram chat with the support bot, and whose words it carries.

    An owner's chat (``owner``) writes into that account's support chat as
    the account; anybody else's writes into a guest chat of its own
    (``guest_chat``). One row per Telegram chat, so a stranger who later
    links keeps the row and only changes which side it writes to.
    """

    __tablename__ = "support_bot_chats"
    __table_args__ = (
        Index(
            "uniq_active_support_bot_chat_per_owner",
            "owner_id",
            unique=True,
            postgresql_where=text("is_active = true AND owner_id IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    chat_id: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    username: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    name: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    owner_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    guest_chat_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("support_guest_chats.id", ondelete="SET NULL"), nullable=True, index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    linked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    last_error_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    owner: Mapped["User | None"] = relationship(foreign_keys=[owner_id], lazy="select")  # noqa: F821
    guest_chat: Mapped["SupportGuestChat | None"] = relationship(foreign_keys=[guest_chat_id], lazy="select")  # noqa: F821
