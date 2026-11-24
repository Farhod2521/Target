from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.db import Base, utcnow


class BusinessLink(Base):
    """One network object a business advertises from.

    For Meta that is the page and ad account pair; for another network, its
    advertiser account. A row is never rewritten onto another object: a
    changed account closes the row (``unbound_at``) and opens a new one, so
    what a business ran from and when stays readable.
    """

    __tablename__ = "business_links"
    __table_args__ = (
        Index(
            "uniq_business_link_per_network",
            "business_id",
            "provider",
            "kind",
            unique=True,
            postgresql_where=text("unbound_at IS NULL"),
            sqlite_where=text("unbound_at IS NULL"),
        ),
        Index(
            "uniq_business_link_per_object",
            "provider",
            "kind",
            "external_id",
            unique=True,
            postgresql_where=text("unbound_at IS NULL"),
            sqlite_where=text("unbound_at IS NULL"),
        ),
        Index("business_links_pair_idx", "page_id", "ad_account_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    business_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True)
    owner_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    provider: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    page_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("page_accounts.id", ondelete="CASCADE"), nullable=True)
    ad_account_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("ad_accounts.id", ondelete="CASCADE"), nullable=True, index=True)
    external_id: Mapped[str] = mapped_column(String(160), nullable=False, default="")
    bound_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    unbound_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    business: Mapped["Business"] = relationship(foreign_keys=[business_id], lazy="select")  # noqa: F821
    page: Mapped["PageAccount | None"] = relationship(foreign_keys=[page_id], lazy="select")  # noqa: F821
    ad_account: Mapped["AdAccount | None"] = relationship(foreign_keys=[ad_account_id], lazy="select")  # noqa: F821
