from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.db import Base, Json, utcnow


class BlockReason(Base):
    """One reason an account may be blocked for, kept by the super admin.

    ``code`` names the ones the code itself refers to (the system's own and
    the catch-all); those cannot be archived. The messages are what the
    account reads at sign-in when the block is shown to it.
    """

    __tablename__ = "block_reasons"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )
    code: Mapped[str | None] = mapped_column(String(32), nullable=True, unique=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    message_uz: Mapped[str] = mapped_column(Text, nullable=False, default="")
    message_ru: Mapped[str] = mapped_column(Text, nullable=False, default="")
    message_en: Mapped[str] = mapped_column(Text, nullable=False, default="")
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    is_archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class AccountBlock(Base):
    """One stretch an account was shut: why, whether it is told, by whom,
    and when it was opened again. The open one has no ``lifted_at``."""

    __tablename__ = "account_blocks"
    __table_args__ = (
        Index("account_blocks_owner_blocked_idx", "owner_id", text("blocked_at DESC")),
        Index(
            "account_blocks_one_open",
            "owner_id",
            unique=True,
            postgresql_where=text("lifted_at IS NULL"),
            sqlite_where=text("lifted_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    reason_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("block_reasons.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    shown_to_user: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    blocked_by_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    blocked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    lifted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    lifted_by_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    lift_note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    reason: Mapped[BlockReason] = relationship(foreign_keys=[reason_id], lazy="select")
    blocked_by: Mapped["User | None"] = relationship(
        foreign_keys=[blocked_by_id], lazy="select"
    )  # noqa: F821


class BlockSuggestion(Base):
    """An account the system thinks Support should look at, and why.

    The system refuses and asks; a person decides. One open row per account
    and reason, counting every time it happened again; Support closes it by
    blocking (``blocked``) or letting it be (``dismissed``).
    """

    __tablename__ = "block_suggestions"
    __table_args__ = (
        Index(
            "block_suggestions_one_open",
            "owner_id",
            "reason_id",
            unique=True,
            postgresql_where=text("resolved_at IS NULL"),
            sqlite_where=text("resolved_at IS NULL"),
        ),
        Index("block_suggestions_open_last", "resolved_at", text("last_at DESC")),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    reason_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("block_reasons.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    detail: Mapped[Any] = mapped_column(Json, nullable=False, default=dict)
    times: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    last_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    resolved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    resolved_by_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    resolution: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    owner: Mapped["User"] = relationship(foreign_keys=[owner_id], lazy="select")  # noqa: F821
    reason: Mapped[BlockReason] = relationship(foreign_keys=[reason_id], lazy="select")
