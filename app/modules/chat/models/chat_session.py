from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.db import Base, utcnow


class ChatSession(Base):
    __tablename__ = "chat_sessions"
    __table_args__ = (
        Index("chat_session_recent_idx", 'owner_id', text("last_message_at DESC")),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    owner_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    page_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("page_accounts.id", ondelete="SET NULL"), nullable=True, index=True)
    ad_account_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("ad_accounts.id", ondelete="SET NULL"), nullable=True, index=True)
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # -- django extras --
    owner: Mapped["User"] = relationship(foreign_keys=[owner_id], lazy="select")  # noqa: F821
    page: Mapped["PageAccount | None"] = relationship(foreign_keys=[page_id], lazy="select")  # noqa: F821
    ad_account: Mapped["AdAccount | None"] = relationship(foreign_keys=[ad_account_id], lazy="select")  # noqa: F821
