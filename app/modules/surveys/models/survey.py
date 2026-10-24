from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import BigInteger, Column, ForeignKey, Table, Boolean, DateTime, Index, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.common.db import Base, Json, utcnow


class Survey(Base):
    __tablename__ = "surveys"
    __table_args__ = (
        Index("surveys_is_acti_bf994c_idx", 'is_active', 'published_at'),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    name: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    audience: Mapped[str] = mapped_column(String(16), nullable=False, default='everyone')
    source_language: Mapped[str] = mapped_column(String(8), nullable=False, default="")
    title: Mapped[Any] = mapped_column(Json, nullable=False, default=dict)
    intro: Mapped[Any] = mapped_column(Json, nullable=False, default=dict)
    state: Mapped[str] = mapped_column(String(16), nullable=False, default='draft')
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


surveys_plans = Table(
    "surveys_plans",
    Base.metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("survey_id", Uuid, ForeignKey("surveys.id", ondelete="CASCADE"), nullable=False),
    Column("plan_id", Uuid, ForeignKey("plans.id", ondelete="CASCADE"), nullable=False),
)


surveys_people = Table(
    "surveys_people",
    Base.metadata,
    Column("id", BigInteger, primary_key=True, autoincrement=True),
    Column("survey_id", Uuid, ForeignKey("surveys.id", ondelete="CASCADE"), nullable=False),
    Column("user_id", Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
)
