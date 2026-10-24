from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, UniqueConstraint, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.db import Base, utcnow


class TelegramChat(Base):
    __tablename__ = "telegram_chats"
    __table_args__ = (
        Index("uniq_active_telegram_chat_per_owner", 'owner_id', unique=True, postgresql_where=text("is_active = true")),
        Index("uniq_active_telegram_chat_id", 'chat_id', unique=True, postgresql_where=text("is_active = true")),
        UniqueConstraint('owner_id', 'chat_id', name="uniq_telegram_chat_per_owner"),
        Index("tg_chat_sugg", 'is_active', 'notify_suggestions'),
        Index("tg_chat_report", 'is_active', 'notify_report'),
        Index("tg_chat_reject", 'is_active', 'notify_rejections'),
        Index("tg_chat_burn", 'is_active', 'notify_spend_guard'),
        Index("tg_chat_daily", 'is_active', 'notify_daily_report'),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    owner_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    chat_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True, default="")
    username: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    notify_suggestions: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    notify_report: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    notify_rejections: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    notify_spend_guard: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    notify_daily_report: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    linked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_error: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    last_error_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # -- django extras --
    owner: Mapped["User"] = relationship(foreign_keys=[owner_id], lazy="select")  # noqa: F821
