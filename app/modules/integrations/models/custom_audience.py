from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.common.db import Base, Json, utcnow
from sqlalchemy.orm import relationship


class CustomAudience(Base):
    __tablename__ = "custom_audiences"
    __table_args__ = (
        UniqueConstraint('provider', 'external_id', name="uniq_audience_per_provider"),
        Index("custom_audi_owner_i_fa00eb_idx", 'owner_id', 'is_ready'),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    owner_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False, index=True, default="")
    external_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True, default="")
    ad_account_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("ad_accounts.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    subtype_raw: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    accepts_members: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    can_seed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    approximate_count_lower: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    approximate_count_upper: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    processing_code: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    processing_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    readiness_code: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    readiness_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    is_ready: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    customer_file_source: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    rule_raw: Mapped[Any] = mapped_column(Json, nullable=False, default=dict)
    retention_days: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    source_kind: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    source_action: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    source_external_id: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    source_label: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    event_raw: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    excluded_event_raw: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    origin_external_id: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    origin_label: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    breadth: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    ratio_raw: Mapped[str] = mapped_column(String(8), nullable=False, default="")
    country_code: Mapped[str] = mapped_column(String(2), nullable=False, default="")
    lookalike_raw: Mapped[Any] = mapped_column(Json, nullable=False, default=dict)
    members_sent: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    members_invalid: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    last_filled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    provider_created_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    provider_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # -- django extras --
    owner: Mapped["User"] = relationship(foreign_keys=[owner_id], lazy="select")  # noqa: F821
    ad_account: Mapped["AdAccount"] = relationship(foreign_keys=[ad_account_id], lazy="select")  # noqa: F821

    @property
    def is_rule_built(self) -> bool:
        return bool(self.rule_raw or self.source_kind) or self.is_lookalike

    @property
    def is_lookalike(self) -> bool:
        return bool(self.lookalike_raw) or bool(self.breadth)

    @property
    def excludes_anybody(self) -> bool:
        return bool(self.excluded_event_raw)

    @property
    def is_counted(self) -> bool:
        return self.approximate_count_upper > 0

    def __str__(self) -> str:
        return self.name or self.external_id
