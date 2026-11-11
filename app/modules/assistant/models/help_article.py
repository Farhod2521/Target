from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.common.db import Base, utcnow


class HelpArticle(Base):
    """One known problem and the steps that solve it, written by the office
    in three languages. The assistant searches these before it answers a
    question about something not working (``help_search``)."""

    __tablename__ = "help_articles"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    # A short name the office finds it by; never shown to a client.
    code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    # The problem as a client would say it.
    problem_uz: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    problem_ru: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    problem_en: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    # The steps, one to a line.
    steps_uz: Mapped[str] = mapped_column(Text, nullable=False, default="")
    steps_ru: Mapped[str] = mapped_column(Text, nullable=False, default="")
    steps_en: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Other words people use for it, in any language, separated by commas.
    keywords: Mapped[str] = mapped_column(Text, nullable=False, default="")
    is_published: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
