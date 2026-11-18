from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column

from app.common.db import Base, utcnow


class AssistantFeedback(Base):
    """What a client said was wrong with the assistant's answers, asked for
    when the assistant prepared a request to Support (owner's decision,
    2026-11-19). The office reads these on «Meta & AI» → AI chat to improve
    the assistant; Support never sees them in the request."""

    __tablename__ = "assistant_feedback"
    __table_args__ = (
        Index("assistant_feedback_status_idx", "status", text("created_at DESC")),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    owner_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    session_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("assistant_sessions.id", ondelete="SET NULL"), nullable=True, index=True)
    # The answer that prepared the request: the one the client judged.
    message_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("assistant_messages.id", ondelete="SET NULL"), nullable=True)
    # The client's question, the assistant's answer to it, and the purpose
    # of the request it prepared - as they were, so the row reads alone.
    question: Mapped[str] = mapped_column(Text, nullable=False, default="")
    answer: Mapped[str] = mapped_column(Text, nullable=False, default="")
    ticket_summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # The client's own words about the answers.
    feedback: Mapped[str] = mapped_column(Text, nullable=False, default="")
    language: Mapped[str] = mapped_column(String(8), nullable=False, default="")
    # ``open`` until the office has read it, then ``done``.
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
