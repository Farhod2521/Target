from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.db import Base, Json, utcnow


class BusinessMember(Base):
    """One person working in one business: one seat, whatever they do there.

    ``roles`` names the ready sets the owner picked (constants.MemberRole)
    and is shown, not checked; what the person may read and change is their
    ``grants``. ``crm_member_id`` is set on a membership kept level with a
    CRM manager's row, which the cabinet's CRM still writes.
    """

    __tablename__ = "business_members"
    __table_args__ = (
        UniqueConstraint("business_id", "user_id", name="uniq_business_member"),
        Index("business_members_user_idx", "user_id", "is_active"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    business_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("businesses.id", ondelete="CASCADE"), nullable=False, index=True)
    owner_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    roles: Mapped[list[Any]] = mapped_column(Json, nullable=False, default=list)
    is_rop: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    joined_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    removed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    crm_member_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("crm_members.id", ondelete="SET NULL"), nullable=True, unique=True)

    business: Mapped["Business"] = relationship(foreign_keys=[business_id], lazy="select")  # noqa: F821
    user: Mapped["User"] = relationship(foreign_keys=[user_id], lazy="select")  # noqa: F821
    grants: Mapped[list["BusinessMemberGrant"]] = relationship(back_populates="member", cascade="all, delete-orphan", lazy="selectin")


class BusinessMemberGrant(Base):
    """What a member may do with one network's part of the business: the
    adverts (``ads``) or the leads it brought (``crm``), to read or to change.
    ``provider`` is the network, or ``other`` for leads no network brought."""

    __tablename__ = "business_member_grants"
    __table_args__ = (
        UniqueConstraint("member_id", "area", "provider", name="uniq_business_member_grant"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    member_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("business_members.id", ondelete="CASCADE"), nullable=False, index=True)
    area: Mapped[str] = mapped_column(String(8), nullable=False)
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    level: Mapped[str] = mapped_column(String(8), nullable=False)

    member: Mapped["BusinessMember"] = relationship(back_populates="grants", foreign_keys=[member_id], lazy="select")
