from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.common.db import Base, utcnow


class MetricsCheck(Base):
    """One closed day of one account: our stored sums against the network's
    own account total, read the night after."""

    __tablename__ = "metrics_checks"
    __table_args__ = (
        UniqueConstraint("ad_account_id", "day", name="uniq_metrics_check_per_day"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    owner_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    ad_account_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("ad_accounts.id", ondelete="CASCADE"), nullable=False, index=True)
    day: Mapped[date] = mapped_column(Date, nullable=False)
    ours: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    theirs: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    differs: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, index=True)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
