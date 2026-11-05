from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import DateTime, ForeignKey, Index, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.db import Base, utcnow


class LapseHold(Base):
    __tablename__ = "lapse_holds"
    __table_args__ = (
        Index("ads_lapsehold_one_per_deadline", 'owner_id', 'ended_at', unique=True, postgresql_where=text("page_id IS NULL"), sqlite_where=text("page_id IS NULL")),
        Index("lapse_holds_one_per_page_release", 'page_id', 'ended_at', unique=True, postgresql_where=text("page_id IS NOT NULL"), sqlite_where=text("page_id IS NOT NULL")),
        Index("lapse_holds_page_idx", 'page_id'),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    owner_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    ended_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    delete_after: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    resumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Set on a hold for one page let go at a renewal; null on a lapsed subscription's.
    page_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("page_accounts.id", ondelete="RESTRICT"), nullable=True)
    # -- django extras --
    owner: Mapped["User"] = relationship(foreign_keys=[owner_id], lazy="select")  # noqa: F821
    @property
    def is_open(self) -> bool:
        return self.resumed_at is None and self.deleted_at is None
