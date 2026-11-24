from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, Uuid, false, text, true
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.common.db import Base, utcnow


class BoardRule(Base):
    """One automatic rule of a board. ``kind`` ``system``: a rule the code
    runs (``code`` names it), with what the superuser may change of it kept
    here; ``stay`` and ``due``: rules of the superuser's own, which move a
    card that stood in a column long enough, or whose time has come."""

    __tablename__ = "board_rules"
    __table_args__ = (Index("uniq_board_rule_code", "code", unique=True), Index("board_rules_board_idx", "board", "position"))

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    board: Mapped[str] = mapped_column(String(16), nullable=False)
    code: Mapped[str] = mapped_column(String(40), nullable=False)
    kind: Mapped[str] = mapped_column(String(16), nullable=False)
    # A rule of the superuser's own: what they call it.
    name: Mapped[str] = mapped_column(String(80), nullable=False, default="")
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default=true())
    from_columns: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    to_column: Mapped[str] = mapped_column(String(24), nullable=False, default="")
    amount: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    unit: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    # Why the card moved, as its history keeps it.
    reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # A rule of the superuser's own: what else must hold of the card
    # (``attempts_min``, ``plans``, ``bill``), and what it does besides or
    # instead of moving it (``due``, ``notify``, ``assign``).
    conditions: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))
    actions: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict, server_default=text("'{}'::jsonb"))
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default=false())
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    updated_by_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
