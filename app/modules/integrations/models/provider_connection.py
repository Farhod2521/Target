from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Index, LargeBinary, SmallInteger, String, UniqueConstraint, Uuid, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.common.db import Base, Json, utcnow
from sqlalchemy.orm import relationship


class ProviderConnection(Base):
    __tablename__ = "provider_connections"
    __table_args__ = (
        UniqueConstraint('owner_id', 'provider', name="uniq_connection_per_provider"),
        Index("uniq_meta_identity_per_provider", 'provider', 'external_user_id', unique=True, postgresql_where=text("NOT (external_user_id = '')")),
        Index("provider_co_provide_0940d9_idx", 'provider', 'status', 'expires_at'),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    owner_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False, index=True, default="")
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default='user_oauth')
    external_user_id: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    external_user_name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    scopes: Mapped[list[Any]] = mapped_column(ARRAY(String(64)), nullable=False, default=list)
    instagram_targets: Mapped[list[Any]] = mapped_column(ARRAY(String(64)), nullable=False, default=list)
    pages_taken: Mapped[Any] = mapped_column(Json, nullable=False, default=list)
    ad_accounts_taken: Mapped[Any] = mapped_column(Json, nullable=False, default=list)
    token_encrypted: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    token_fingerprint: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default='active')
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_code: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    action_required_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    action_refusals: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    # -- django extras --
    owner: Mapped["User"] = relationship(foreign_keys=[owner_id], lazy="select")  # noqa: F821
