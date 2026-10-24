from __future__ import annotations

import uuid

from sqlalchemy import BigInteger, ForeignKey, Integer, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.common.db import Base


class Group(Base):
    """Django's ``auth_group``: the office roles hang off these names."""

    __tablename__ = "auth_group"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(150), nullable=False, unique=True)


class UserGroup(Base):
    """Django's ``users_groups`` through table for ``User.groups``."""

    __tablename__ = "users_groups"
    __table_args__ = (UniqueConstraint("user_id", "group_id", name="users_groups_user_id_group_id_uniq"),)

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    group_id: Mapped[int] = mapped_column(Integer, ForeignKey("auth_group.id", ondelete="CASCADE"), nullable=False, index=True)
