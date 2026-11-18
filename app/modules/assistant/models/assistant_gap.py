from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column

from app.common.db import Base, Json, utcnow


class AssistantGap(Base):
    """One question the assistant could not answer, as the office reads it.

    The same question asked again is the same row (``hits``), so what is
    asked most is what gets written first. ``kind`` says what is missing:
    words a person can write (``answer``), or something to be built
    (``tool``). An answer written for it is a help article (``article_id``)
    the assistant finds from then on."""

    __tablename__ = "assistant_gaps"
    __table_args__ = (
        Index("assistant_gaps_status_idx", "status", text("hits DESC")),
        Index("assistant_gaps_recent_idx", text("last_asked_at DESC")),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    # The question as a short title, in Uzbek.
    topic: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    # ``answer`` or ``tool`` (``core.assistant.tools``).
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="answer")
    # What has to be added, in the assistant's own short words; empty when
    # the search found nothing and the assistant said no more.
    missing: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # The last person's own words, and the language they wrote in.
    question: Mapped[str] = mapped_column(Text, nullable=False, default="")
    language: Mapped[str] = mapped_column(String(8), nullable=False, default="")
    # What the assistant searched for and did not find.
    queries: Mapped[Any] = mapped_column(Json, nullable=False, default=list)
    # The last few askings, newest first: the words, when, who, which answer.
    samples: Mapped[Any] = mapped_column(Json, nullable=False, default=list)
    hits: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    last_asked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    # ``open``, ``answered`` or ``dismissed`` (``constants.GapStatus``).
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="open")
    article_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("help_articles.id", ondelete="SET NULL"), nullable=True, index=True)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
