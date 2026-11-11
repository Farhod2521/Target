from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column

from app.common.db import Base, utcnow


class AssistantSession(Base):
    """One thread of the cabinet's one chat: the assistant's answers and
    Support's people's, in the order they were written."""

    __tablename__ = "assistant_sessions"
    __table_args__ = (
        Index("assistant_session_recent_idx", "owner_id", text("last_message_at DESC")),
        Index(
            "assistant_session_support_idx",
            "owner_id",
            text("support_at DESC"),
            postgresql_where=text("support_at IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    owner_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    # The page the cabinet was on when the thread began: its figures are the
    # ones the answers quote. A thread of no page is shown on every page.
    page_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("page_accounts.id", ondelete="SET NULL"), nullable=True, index=True)
    ad_account_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("ad_accounts.id", ondelete="SET NULL"), nullable=True, index=True)
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # When Support was last part of this thread: a ticket sent from it, a
    # message written to a person, or a person's reply. The newest one is
    # where Support's next message is shown.
    support_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
