from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.db import Base, Json, utcnow


class BusinessSubtype(Base):
    """A narrower kind of business under a direction: «Oshxona mebeli»
    under «Mebel».

    Nobody keeps this list by hand. The assistant makes a row the first time
    a customer names a kind that is not there (``origin`` ``ai``,
    ``is_checked`` false until the office has looked), and looks for one
    before making it: ``name_key`` is the name with its case, apostrophes
    and spaces levelled, unique under the direction. ``synonyms`` are the
    other words customers call it by. Two rows that turn out to be one kind
    are merged: the one given up keeps ``merged_into_id`` and is never
    offered again.
    """

    __tablename__ = "business_subtypes"
    __table_args__ = (
        UniqueConstraint("direction_id", "name_key", name="uniq_business_subtype_name"),
        CheckConstraint(text("NOT (name_key = '')"), name="business_subtype_has_a_name"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    direction_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("business_categories.id", ondelete="CASCADE"), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    name_key: Mapped[str] = mapped_column(String(80), nullable=False)
    synonyms: Mapped[list[Any]] = mapped_column(Json, nullable=False, default=list)
    origin: Mapped[str] = mapped_column(String(8), nullable=False)
    is_checked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    merged_into_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("business_subtypes.id", ondelete="SET NULL"), nullable=True, index=True)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)

    direction: Mapped["BusinessCategory"] = relationship(foreign_keys=[direction_id], lazy="select")  # noqa: F821
