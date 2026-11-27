from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.db import Base, utcnow


class BusinessTypeRule(Base):
    """What the office advises every business of one direction.

    Two goals, not one: the first is offered with its reason, the second is
    the one to offer instead when ``when_second`` holds. ``never_say`` is
    what an advert of this kind of business must not promise. A direction
    with no row is advised nothing, and the assistant says so.
    """

    __tablename__ = "business_type_rules"
    __table_args__ = (
        UniqueConstraint("direction_id", name="uniq_business_type_rule"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    direction_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("business_categories.id", ondelete="CASCADE"), nullable=False)
    goal_first: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    reason_first: Mapped[str] = mapped_column(Text, nullable=False, default="")
    goal_second: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    when_second: Mapped[str] = mapped_column(Text, nullable=False, default="")
    never_say: Mapped[str] = mapped_column(Text, nullable=False, default="")
    updated_by_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)

    direction: Mapped["BusinessCategory"] = relationship(foreign_keys=[direction_id], lazy="select")  # noqa: F821
