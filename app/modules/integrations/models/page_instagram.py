from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.common.db import Base, utcnow
from sqlalchemy.orm import relationship


class PageInstagram(Base):
    __tablename__ = "page_instagrams"
    __table_args__ = (
        UniqueConstraint('page_id', 'instagram_user_id', name="uniq_instagram_per_page"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    owner_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    page_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("page_accounts.id", ondelete="CASCADE"), nullable=False, index=True)
    instagram_user_id: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    username: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_linked: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # -- django extras --
    owner: Mapped["User"] = relationship(foreign_keys=[owner_id], lazy="select")  # noqa: F821
    page: Mapped["PageAccount"] = relationship(foreign_keys=[page_id], lazy="select")  # noqa: F821

    @property
    def is_page_own(self) -> bool:
        return self.instagram_user_id == self.page.instagram_user_id

    def __str__(self) -> str:
        return f"@{self.username}" if self.username else self.instagram_user_id
