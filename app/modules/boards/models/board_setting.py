from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.common.db import Base, utcnow


class BoardSetting(Base):
    """When a board went live: sign-ups and events before it are ignored.
    On Uzaytirish also the manager every new card goes to."""

    __tablename__ = "board_settings"

    board: Mapped[str] = mapped_column(String(16), primary_key=True)
    live_since: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    manager_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
