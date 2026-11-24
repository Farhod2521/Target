from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.common.db import Base, utcnow


class BoardSettingEvent(Base):
    """One change of a board's settings: who added, changed or took off a
    column, a reason, a button or a rule, and what it read before and after."""

    __tablename__ = "board_setting_events"
    __table_args__ = (Index("board_setting_events_board_idx", "board", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    board: Mapped[str] = mapped_column(String(16), nullable=False)
    # column, reason, button, rule
    area: Mapped[str] = mapped_column(String(16), nullable=False)
    # add, edit, remove, order
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    # What was changed, as the settings name it.
    name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    # What changed of it, in words: «Nomi: A → B».
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    actor_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
