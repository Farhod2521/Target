from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.common.db import Base, Json, utcnow


class OfficeAiMessage(Base):
    """One row of an office thread: the question, or the answer."""

    __tablename__ = "office_ai_messages"
    __table_args__ = (
        Index("office_ai_message_thread_idx", "thread_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    staff_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    thread_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("office_ai_threads.id", ondelete="CASCADE"), nullable=False, index=True)
    # ``user`` or ``ai`` (``constants.Author``).
    author: Mapped[str] = mapped_column(String(8), nullable=False, default="")
    text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    html: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="done")
    masked_figures: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # On an answer: ``lookups`` (what was read to write it), ``stopped``.
    meta: Mapped[Any] = mapped_column(Json, nullable=False, default=dict)
