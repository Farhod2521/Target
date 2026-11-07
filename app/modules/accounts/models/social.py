from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.common.db import Base, utcnow


class SocialIdentity(Base):
    """A Google (later Telegram, Facebook) account that signs one of ours in.

    Tied by the provider's own id, which never changes; ``email`` is what
    the provider said at the last sign-in, for the settings page and the
    office. One of each provider per account, one account per provider id.
    """

    __tablename__ = "social_identities"
    __table_args__ = (
        UniqueConstraint("provider", "subject", name="uniq_social_identity"),
        UniqueConstraint("owner_id", "provider", name="uniq_social_identity_owner"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    owner_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    subject: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    email: Mapped[str] = mapped_column(String(254), nullable=False, default="")
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
