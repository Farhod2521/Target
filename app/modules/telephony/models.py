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
    LargeBinary,
    String,
    Text,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.common.db import Base, utcnow


class PhoneConnection(Base):
    """One exchange tied to us. ``owner_id`` empty: the office's own, of
    which there is one. The exchange's password is never kept, only the key
    it gave for it."""

    __tablename__ = "phone_connections"
    __table_args__ = (
        Index(
            "uniq_phone_connection_office",
            "provider",
            unique=True,
            postgresql_where=text("owner_id IS NULL"),
        ),
        Index("uniq_phone_connection_hook_key", "hook_key", unique=True),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )
    owner_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )
    provider: Mapped[str] = mapped_column(String(16), nullable=False)
    tenant: Mapped[str] = mapped_column(String(40), nullable=False)
    api_email: Mapped[str] = mapped_column(String(254), nullable=False)
    api_token: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    hook_key: Mapped[str] = mapped_column(String(64), nullable=False)
    hook_set_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error: Mapped[str] = mapped_column(Text, nullable=False, default="")
    connected_by_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )


class PhoneExtension(Base):
    """An internal number of the exchange and the person who answers it.
    A person holds one number of a connection."""

    __tablename__ = "phone_extensions"
    __table_args__ = (
        Index("uniq_phone_extension_number", "connection_id", "number", unique=True),
        Index(
            "uniq_phone_extension_user",
            "connection_id",
            "user_id",
            unique=True,
            postgresql_where=text("user_id IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )
    connection_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("phone_connections.id", ondelete="CASCADE"), nullable=False
    )
    number: Mapped[str] = mapped_column(String(16), nullable=False)
    title: Mapped[str] = mapped_column(String(60), nullable=False, default="")
    sip_password: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    softphone: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # The exchange no longer lists it. Registering a number that is not
    # there gets the whole office's address blocked, so it is never offered.
    is_gone: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # The exchange refused this number's password to the browser phone.
    # Until the password changes or the office gives the number again, the
    # phone is not started: repeated refusals get the office's address blocked.
    sip_refused_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class PhoneHookEvent(Base):
    """What the exchange sent, as it came."""

    __tablename__ = "phone_hook_events"
    __table_args__ = (
        Index("phone_hook_events_time_idx", "connection_id", "received_at"),
        Index("phone_hook_events_call_idx", "connection_id", "call_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    connection_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("phone_connections.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    call_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


class PhoneCall(Base):
    """A finished call as the exchange saved it. ``number`` is the other
    side, written the way a client's phone is kept, so the client is found
    by it whenever the call is read - also one who signed up afterwards."""

    __tablename__ = "phone_calls"
    __table_args__ = (
        Index("uniq_phone_call", "connection_id", "call_id", unique=True),
        Index("phone_calls_time_idx", "connection_id", "started_at"),
        Index("phone_calls_number_idx", "number"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    connection_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("phone_connections.id", ondelete="CASCADE"), nullable=False
    )
    call_id: Mapped[str] = mapped_column(String(64), nullable=False)
    direction: Mapped[str] = mapped_column(String(8), nullable=False)
    answered: Mapped[bool] = mapped_column(Boolean, nullable=False)
    number: Mapped[str] = mapped_column(String(20), nullable=False)
    extension: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    line: Mapped[str] = mapped_column(String(20), nullable=False, default="")
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    duration_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    talk_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # UTeL's own link. It opens without a key, so it never leaves the server.
    recording_url: Mapped[str] = mapped_column(Text, nullable=False, default="")


class PhoneLiveCall(Base):
    """A call going on right now, by what the exchange has said so far.
    The row goes when the call ends."""

    __tablename__ = "phone_live_calls"
    __table_args__ = (
        Index("uniq_phone_live_call", "connection_id", "call_id", unique=True),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    connection_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("phone_connections.id", ondelete="CASCADE"), nullable=False
    )
    call_id: Mapped[str] = mapped_column(String(64), nullable=False)
    direction: Mapped[str] = mapped_column(String(8), nullable=False)
    number: Mapped[str] = mapped_column(String(20), nullable=False)
    extension: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    state: Mapped[str] = mapped_column(String(8), nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )
