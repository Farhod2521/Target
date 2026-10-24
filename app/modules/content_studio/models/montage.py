from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, Integer, SmallInteger, String, Text, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.db import Base, Json, utcnow


class Montage(Base):
    __tablename__ = "montages"
    __table_args__ = (
        Index("montages_owner_i_6f7e7b_idx", 'owner_id', text("created_at DESC")),
        Index("montages_owner_i_93af9d_idx", 'owner_id', 'status'),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    owner_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    source: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    page_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("page_accounts.id", ondelete="SET NULL"), nullable=True, index=True)
    brand: Mapped[Any] = mapped_column(Json, nullable=False, default=dict)
    source_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(16), nullable=False, index=True, default='queued')
    target_seconds: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=30)
    aspect_ratio: Mapped[str] = mapped_column(String(8), nullable=False, default='9:16')
    pace: Mapped[str] = mapped_column(String(16), nullable=False, default='dynamic')
    call_to_action: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    brief: Mapped[str] = mapped_column(Text, nullable=False, default="")
    sound: Mapped[str] = mapped_column(String(8), nullable=False, default='clean')
    subtitles: Mapped[str] = mapped_column(String(4), nullable=False, default='on')
    video_language: Mapped[str] = mapped_column(String(2), nullable=False, default='uz')
    prepared: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    source_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    transcript: Mapped[Any] = mapped_column(Json, nullable=False, default=list)
    transcript_fixes: Mapped[Any | None] = mapped_column(Json, nullable=True)
    transcript_review: Mapped[Any] = mapped_column(Json, nullable=False, default=list)
    faces: Mapped[Any] = mapped_column(Json, nullable=False, default=list)
    language: Mapped[str] = mapped_column(String(8), nullable=False, default="")
    cut: Mapped[Any] = mapped_column(Json, nullable=False, default=dict)
    plan_raw: Mapped[Any] = mapped_column(Json, nullable=False, default=dict)
    plan_prompt: Mapped[str] = mapped_column(String(8), nullable=False, default="")
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    captions_srt: Mapped[str] = mapped_column(Text, nullable=False, default="")
    provider_source_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    provider_captions_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    render_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    output: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    output_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    qa: Mapped[Any] = mapped_column(Json, nullable=False, default=dict)
    timings: Mapped[Any] = mapped_column(Json, nullable=False, default=dict)
    failure: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    failure_detail: Mapped[str] = mapped_column(Text, nullable=False, default="")
    attempts: Mapped[Any] = mapped_column(Json, nullable=False, default=dict)
    speech_cost_micros: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    render_cost_micros: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    service_currency: Mapped[str] = mapped_column(String(3), nullable=False, default="")
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # -- django extras --
    owner: Mapped["User"] = relationship(foreign_keys=[owner_id], lazy="select")  # noqa: F821
    page: Mapped["PageAccount | None"] = relationship(foreign_keys=[page_id], lazy="select")  # noqa: F821
