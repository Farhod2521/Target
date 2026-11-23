from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Uuid, false
from sqlalchemy.orm import Mapped, mapped_column

from app.common.db import Base, utcnow


class BoardReason(Base):
    """One reason a person picks on a board: why a Sales card is closed, why
    a client does not renew, why a card is moved by hand, why a call did not
    reach the client. ``code`` is what a card keeps and never changes; the
    superuser renames, reorders and adds reasons. Archived, never deleted:
    cards and reports keep the one they had."""

    __tablename__ = "board_reasons"
    __table_args__ = (
        Index("uniq_board_reason_code", "board", "purpose", "code", unique=True),
        Index("board_reasons_order_idx", "board", "purpose", "position"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    board: Mapped[str] = mapped_column(String(16), nullable=False)
    purpose: Mapped[str] = mapped_column(String(16), nullable=False)
    code: Mapped[str] = mapped_column(String(24), nullable=False)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # Picked with a line written («Boshqa»).
    note_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    is_archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    # One the board came with: its code is what old cards and the rules carry.
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
