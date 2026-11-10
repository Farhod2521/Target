from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, SmallInteger, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.common.db import Base, utcnow


class SurveyHelpOption(Base):
    """A survey answer that asks for a specialist: choosing it opens a
    Support ticket. Kept beside the survey, which stays as it is."""

    __tablename__ = "survey_help_options"
    __table_args__ = (Index("uniq_survey_help_option", "question_id", "option_index", unique=True),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    question_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("survey_questions.id", ondelete="CASCADE"), nullable=False)
    option_index: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    set_by_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
