from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Uuid, false
from sqlalchemy.orm import Mapped, mapped_column

from app.common.db import Base, utcnow


class BoardButton(Base):
    """One button a column's cards show. ``action`` is a button the code
    knows («Gaplashildi», «Hal qilindi», …) or ``go``: the superuser's own
    button that only moves the card. ``code`` is what the screen sends back.
    An empty ``label`` reads the action's own words; an empty ``to_column``
    leaves the move to the action's rule."""

    __tablename__ = "board_buttons"
    __table_args__ = (
        Index("uniq_board_button_code", "board", "column_code", "code", unique=True),
        Index("board_buttons_order_idx", "board", "column_code", "position"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    board: Mapped[str] = mapped_column(String(16), nullable=False)
    column_code: Mapped[str] = mapped_column(String(24), nullable=False)
    code: Mapped[str] = mapped_column(String(24), nullable=False)
    action: Mapped[str] = mapped_column(String(24), nullable=False)
    label: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    to_column: Mapped[str] = mapped_column(String(24), nullable=False, default="")
    # The superuser's own button: whether it asks for a time (``required``, ``optional``) and for a line.
    due: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    note_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # One the column came with.
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
