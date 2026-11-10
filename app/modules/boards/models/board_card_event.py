from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column

from app.common.db import Base, utcnow


class BoardCardEvent(Base):
    """One line of a card's history. ``ref`` names the fact a rule saw (a
    payment, a refused launch), so the same fact is written once."""

    __tablename__ = "board_card_events"
    __table_args__ = (
        Index("board_card_events_card_idx", "card_id", "created_at"),
        Index("uniq_board_card_event_ref", "card_id", "ref", unique=True, postgresql_where=text("ref <> ''")),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    card_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("board_cards.id", ondelete="CASCADE"), nullable=False)
    owner_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    from_column: Mapped[str] = mapped_column(String(24), nullable=False, default="")
    to_column: Mapped[str] = mapped_column(String(24), nullable=False, default="")
    actor_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    ref: Mapped[str] = mapped_column(String(100), nullable=False, default="")
