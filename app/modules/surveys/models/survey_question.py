from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, SmallInteger, String, UniqueConstraint, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.db import Base, Json, utcnow


class SurveyQuestion(Base):
    __tablename__ = "survey_questions"
    __table_args__ = (
        UniqueConstraint('survey_id', 'position', name="uniq_survey_question_position"),
        CheckConstraint(text("(min_value IS NULL) OR (max_value IS NULL) OR ((max_value > min_value) AND (max_value <= 10))"), name="survey_question_number_bounds"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    survey_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("surveys.id", ondelete="CASCADE"), nullable=False, index=True)
    position: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    text: Mapped[Any] = mapped_column(Json, nullable=False, default=dict)
    options: Mapped[Any] = mapped_column(Json, nullable=False, default=list)
    allows_many: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    min_value: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    max_value: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    is_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    show_if: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    show_options: Mapped[Any] = mapped_column(Json, nullable=False, default=list)
    # -- django extras --
    survey: Mapped["Survey"] = relationship(foreign_keys=[survey_id], lazy="select")  # noqa: F821
