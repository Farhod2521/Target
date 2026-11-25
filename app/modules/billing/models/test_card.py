from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, LargeBinary, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.db import Base, utcnow


class TestCard(Base):
    """A card the superuser binds in the office «Testing», apart from the
    account's own card: binding one here never touches the cabinet's card
    or its autopay. Only the office's trial payments use it.
    """

    __tablename__ = "test_cards"
    __test__ = False  # not a pytest class

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    actor_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    # Multicard's binding page; its callback names the card by it.
    session_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    # ``pending`` (page open), ``active`` or ``revoked``.
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    token_encrypted: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    pan: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    ps: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    holder: Mapped[str] = mapped_column(String(100), nullable=False, default="")
    bound_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    actor: Mapped["User"] = relationship(foreign_keys=[actor_id], lazy="select")  # noqa: F821, UP037
