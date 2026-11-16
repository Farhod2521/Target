from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.common.db import Base, Json, utcnow


class ChatTemplate(Base):
    """A chat advert's greeting and ready questions, kept under a name so the
    next advert on the same page can open with them."""

    __tablename__ = "chat_templates"
    __table_args__ = (Index("chat_template_page_idx", "owner_id", "page_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    owner_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    page_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("page_accounts.id", ondelete="CASCADE"), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    welcome_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    questions: Mapped[Any] = mapped_column(Json, nullable=False, default=list)
    # The answer sent by itself for the question at the same place; "" for none.
    answers: Mapped[Any] = mapped_column(Json, nullable=False, default=list)
