from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.common.db import Base, utcnow


class Broadcast(Base):
    """One message from the office, to the bot, the channel, the site, or any
    of them. Written as a draft; ``started_at`` is when it went out, and the
    site shows it from then on."""

    __tablename__ = "broadcasts"
    __table_args__ = (Index("broadcasts_site_idx", "to_site", "started_at"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    title: Mapped[str] = mapped_column(String(120), nullable=False, default="")
    body: Mapped[str] = mapped_column(Text, nullable=False, default="")
    image: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    to_bot: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    to_channel: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    to_site: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="draft")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # The picture as Telegram keeps it, after its first upload.
    photo_id: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    channel_message_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    channel_error: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


class BroadcastDelivery(Base):
    """One bot chat a broadcast goes to: written for every reader when it
    starts, then claimed, sent and stamped one by one."""

    __tablename__ = "broadcast_deliveries"
    __table_args__ = (
        UniqueConstraint("broadcast_id", "chat_id", name="uniq_broadcast_delivery_chat"),
        Index("broadcast_deliveries_status_idx", "broadcast_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    broadcast_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("broadcasts.id", ondelete="CASCADE"), nullable=False)
    owner_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    chat_id: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    message_id: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    error: Mapped[str] = mapped_column(String(255), nullable=False, default="")


class BroadcastSeen(Base):
    """When a reader last opened the site's news: anything started after is
    unread."""

    __tablename__ = "broadcast_seen"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    owner_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True)
    seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
