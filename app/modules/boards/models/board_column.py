from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, SmallInteger, String, Uuid, false
from sqlalchemy.orm import Mapped, mapped_column

from app.common.db import Base, utcnow


class BoardColumn(Base):
    """One column of a board. ``code`` is what the rules move cards by and
    never changes; the superuser renames and reorders columns, adds their
    own (``is_custom``) and takes those off the board again (hidden, never
    deleted: the cards' history names them)."""

    __tablename__ = "board_columns"
    __table_args__ = (
        Index("uniq_board_column_code", "board", "code", unique=True),
        Index("board_columns_order_idx", "board", "position"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    board: Mapped[str] = mapped_column(String(16), nullable=False)
    code: Mapped[str] = mapped_column(String(24), nullable=False)
    name: Mapped[str] = mapped_column(String(40), nullable=False)
    position: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    is_final: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_visible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Added in the office by the superuser, not one the rules were written for.
    is_custom: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    # Sales: a card standing here was talked to, so a Start payment starts
    # its discount from here (Bog'lanildi and the discount columns always).
    is_talked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    updated_by_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
