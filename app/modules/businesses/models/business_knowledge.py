from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.db import Base, Json, utcnow


class BusinessKnowledge(Base):
    """What one business has told us about itself, kept between adverts.

    ``data`` is one document (see ``services.knowledge``): what the business
    does, the things it sells, the facts about it, and the changes somebody
    proposed that are waiting for a yes. It is never written whole from
    outside: a write is a list of small changes applied under a row lock,
    and ``version`` grows by one each time, so the advert chat and the
    cabinet's chat can both add to it without one undoing the other.

    The row stands apart from ``businesses`` on purpose: every old reader of
    a profile loads that table, and none of them needs this.
    """

    __tablename__ = "business_knowledge"
    __table_args__ = (
        UniqueConstraint("business_id", name="uniq_business_knowledge"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    business_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False)
    subtype_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("business_subtypes.id", ondelete="SET NULL"), nullable=True, index=True)
    type_state: Mapped[str] = mapped_column(String(12), nullable=False, default="unset")
    data: Mapped[dict[str, Any]] = mapped_column(Json, nullable=False, default=dict)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    business: Mapped["Business"] = relationship(foreign_keys=[business_id], lazy="select")  # noqa: F821
    subtype: Mapped["BusinessSubtype | None"] = relationship(foreign_keys=[subtype_id], lazy="select")  # noqa: F821
