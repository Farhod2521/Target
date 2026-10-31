from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.common.db import Base, utcnow


class RefusalAnswer(Base):
    __tablename__ = "chat_refusal_answers"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    key: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, default="")
    provider_title: Mapped[str] = mapped_column(Text, nullable=False, default="")
    provider_message: Mapped[str] = mapped_column(Text, nullable=False, default="")
    answer_uz: Mapped[str] = mapped_column(Text, nullable=False, default="")
    answer_ru: Mapped[str] = mapped_column(Text, nullable=False, default="")
    answer_en: Mapped[str] = mapped_column(Text, nullable=False, default="")
    prompt_version: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    hits: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    held: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    edited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
