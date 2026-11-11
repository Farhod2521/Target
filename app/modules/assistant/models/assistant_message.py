from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column

from app.common.db import Base, Json, utcnow


class AssistantMessage(Base):
    """One row of a thread: the client's words, the assistant's answer, or a
    reply from a person in Support (``author``)."""

    __tablename__ = "assistant_messages"
    __table_args__ = (
        Index("assistant_thread_idx", "owner_id", "session_id", "created_at"),
        Index(
            "assistant_messages_support_message_uniq",
            "support_message_id",
            unique=True,
            postgresql_where=text("support_message_id IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    owner_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    session_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("assistant_sessions.id", ondelete="CASCADE"), nullable=False, index=True)
    # ``user``, ``ai`` or ``staff`` (``constants.Author``).
    author: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    html: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="done")
    masked_figures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # What can be pressed under an answer: a ticket, a change, an offer -
    # each with its own state (``constants.ButtonKind``, ``ButtonState``).
    buttons: Mapped[Any] = mapped_column(Json, nullable=False, default=list)
    # Short answers offered as the client's next words.
    replies: Mapped[Any] = mapped_column(Json, nullable=False, default=list)
    # The waiting-list line a question replied to, or who in Support wrote.
    meta: Mapped[Any] = mapped_column(Json, nullable=False, default=dict)
    # This row is that support-chat message. No foreign key: the support
    # chat keeps and erases its own rows.
    support_message_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
