from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.db import Base, utcnow

if TYPE_CHECKING:
    from app.modules.accounts.models import User


class BoardCard(Base):
    """A client on a board: a lead on Sales, a ticket on Support. A client
    has at most one card per board, ever: a solved ticket is reopened, not
    replaced, so one person in Support keeps working with them."""

    __tablename__ = "board_cards"
    __table_args__ = (
        Index("uniq_board_card_owner", "board", "owner_id", unique=True),
        Index("board_cards_column_idx", "board", "column_code", "column_since"),
        Index("board_cards_manager_idx", "board", "manager_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    board: Mapped[str] = mapped_column(String(16), nullable=False)
    owner_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    column_code: Mapped[str] = mapped_column(String(24), nullable=False)
    # The sales manager, or the Support person who first took the ticket.
    manager_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    # Sales: what the last call came to (``contacted``, ``no_contact``).
    contact_mark: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    # Sales: the client asked for help; a ticket opens as soon as they pay.
    needs_support: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # Support: why the ticket is open, each reason once, oldest first.
    reasons: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    column_since: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    close_reason: Mapped[str] = mapped_column(String(24), nullable=False, default="")
    close_note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    owner: Mapped[User] = relationship(foreign_keys=[owner_id], lazy="select")
    manager: Mapped[User | None] = relationship(foreign_keys=[manager_id], lazy="select")
