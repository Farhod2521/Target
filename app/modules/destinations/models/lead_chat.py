from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.db import Base, utcnow


class LeadChat(Base):
    """A Telegram group or channel the customer bot posts an owner's leads in."""

    __tablename__ = "lead_chats"
    __table_args__ = (
        UniqueConstraint("owner_id", "chat_id", name="uniq_lead_chat_per_owner"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    owner_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    chat_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    title: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    broken_reason: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    linked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    broken_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # When getChat last confirmed it is private and the bot is in it.
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str] = mapped_column(String(255), nullable=False, default="")

    owner: Mapped["User"] = relationship(foreign_keys=[owner_id], lazy="select")  # noqa: F821


class LeadChatPair(Base):
    """Which chat one page and ad account pair's leads go to. Several pairs
    may share a chat; a pair has one."""

    __tablename__ = "lead_chat_pairs"
    __table_args__ = (
        UniqueConstraint("page_id", "ad_account_id", name="uniq_lead_chat_pair"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    owner_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    lead_chat_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("lead_chats.id", ondelete="CASCADE"), nullable=False, index=True)
    page_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("page_accounts.id", ondelete="CASCADE"), nullable=False)
    ad_account_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("ad_accounts.id", ondelete="CASCADE"), nullable=False)
    # Leads from this moment on: linking does not post the backlog.
    linked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    lead_chat: Mapped[LeadChat] = relationship(foreign_keys=[lead_chat_id], lazy="joined")
