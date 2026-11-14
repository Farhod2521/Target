from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, SmallInteger, String, Text, Uuid, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.db import Base, utcnow

if TYPE_CHECKING:
    from app.modules.accounts.models import User


class BoardCard(Base):
    """A client on a board: a lead on Sales, a ticket on Support, a term
    running out on Uzaytirish. On Sales and Support a client has at most one
    card, ever: a solved ticket is reopened, not replaced, so one person in
    Support keeps working with them. On Uzaytirish each term that runs out
    has its own card (``term_ends_at``), and the old ones stay as history."""

    __tablename__ = "board_cards"
    __table_args__ = (
        Index(
            "uniq_board_card_owner",
            "board",
            "owner_id",
            unique=True,
            postgresql_where=text("term_ends_at IS NULL"),
        ),
        Index(
            "uniq_board_card_term",
            "board",
            "owner_id",
            "term_ends_at",
            unique=True,
            postgresql_where=text("term_ends_at IS NOT NULL"),
        ),
        Index("board_cards_column_idx", "board", "column_code", "column_since"),
        Index("board_cards_manager_idx", "board", "manager_id"),
        Index("board_cards_due_idx", "board", "due_at", postgresql_where=text("due_at IS NOT NULL")),
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
    # Sales: how many times «Bog'lanilmadi» was pressed.
    attempts: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0, server_default="0")
    # The time the person working the card set for its next step.
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Support: why the ticket is open, each reason once, oldest first.
    reasons: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, nullable=False, default=list)
    opened_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    column_since: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    close_reason: Mapped[str] = mapped_column(String(24), nullable=False, default="")
    close_note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # Uzaytirish: the plan the term was on, the moment the term ends, and
    # the bill whose payment renewed it.
    plan_code: Mapped[str] = mapped_column(String(32), nullable=False, default="", server_default="")
    term_ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    invoice_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("invoices.id", ondelete="SET NULL"), nullable=True, index=True)
    owner: Mapped[User] = relationship(foreign_keys=[owner_id], lazy="select")
    manager: Mapped[User | None] = relationship(foreign_keys=[manager_id], lazy="select")
