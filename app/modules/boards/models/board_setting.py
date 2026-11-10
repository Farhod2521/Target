from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from app.common.db import Base, utcnow


class BoardSetting(Base):
    """When a board went live. Sign-ups and events before it are ignored."""

    __tablename__ = "board_settings"

    board: Mapped[str] = mapped_column(String(16), primary_key=True)
    live_since: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
