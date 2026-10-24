from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, String, UniqueConstraint, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.db import Base, Json, utcnow


class SurveyResponse(Base):
    __tablename__ = "survey_responses"
    __table_args__ = (
        UniqueConstraint('owner_id', 'survey_id', name="uniq_survey_response_per_owner"),
        Index("survey_resp_survey__05a83e_idx", 'survey_id', text("created_at DESC")),
        Index("survey_response_recent_idx", text("created_at DESC")),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    owner_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    survey_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("surveys.id", ondelete="RESTRICT"), nullable=False, index=True)
    language: Mapped[str] = mapped_column(String(8), nullable=False, default="")
    channel: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    answers: Mapped[Any] = mapped_column(Json, nullable=False, default=list)
    # -- django extras --
    owner: Mapped["User"] = relationship(foreign_keys=[owner_id], lazy="select")  # noqa: F821
    survey: Mapped["Survey"] = relationship(foreign_keys=[survey_id], lazy="select")  # noqa: F821
