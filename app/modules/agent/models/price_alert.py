from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
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


class PriceAlert(Base):
    """TZ 1.7: one group whose result costs three times its usual price."""

    __tablename__ = "agent_price_alerts"
    __table_args__ = (
        Index(
            "uniq_open_price_alert",
            "owner_id",
            "provider",
            "adset_external_id",
            unique=True,
            postgresql_where=text("closed_at IS NULL"),
            sqlite_where=text("closed_at IS NULL"),
        ),
        Index("agent_price_owner_open", "owner_id", "closed_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    ad_account_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("ad_accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    adset_external_id: Mapped[str] = mapped_column(
        String(128), nullable=False, default=""
    )
    # The advert that rose, or empty when the group rose as a whole.
    ad_external_id: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    name: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # What one result is: `lead`, `chat`, ... or `site:<event>` (TZ 3.3).
    result_kind: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="")
    spend_minor: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    results: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cost_minor: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    cost_usual_minor: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # How many usual prices, in hundredths.
    times: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    baseline_source: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    baseline_adverts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    causes: Mapped[Any] = mapped_column(Json, nullable=False, default=list)
    telegram_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    telegram_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    answer: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    answered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    hidden_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    cost_after_7d_minor: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # -- django extras --
    owner: Mapped["User"] = relationship(foreign_keys=[owner_id], lazy="select")  # noqa: F821
    ad_account: Mapped["AdAccount"] = relationship(foreign_keys=[ad_account_id], lazy="select")  # noqa: F821
