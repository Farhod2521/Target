from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.db import Base, Json, utcnow


class GuardAlert(Base):
    """One thing the half-hourly guard found about a group or an advert.

    Open until what it says is over. ``step`` is how far it has gone and
    ``said_step`` how far the owner has been told: a message goes out only
    while the second is behind the first, so the same step is never said
    twice. ``baseline`` is the day's figures at a stop - what the group's
    count restarts from when it is switched back on that day.
    """

    __tablename__ = "agent_guard_alerts"
    __table_args__ = (
        Index(
            "uniq_open_guard_alert",
            "owner_id",
            "provider",
            "external_id",
            "kind",
            unique=True,
            postgresql_where=text("closed_at IS NULL"),
            sqlite_where=text("closed_at IS NULL"),
        ),
        Index("agent_guard_owner_open", "owner_id", "closed_at"),
        Index(
            "agent_guard_answer_log",
            "answer_log_id",
            postgresql_where=text("answer_log_id IS NOT NULL"),
            sqlite_where=text("answer_log_id IS NOT NULL"),
        ),
        Index(
            "agent_guard_action_log",
            "action_log_id",
            postgresql_where=text("action_log_id IS NOT NULL"),
            sqlite_where=text("action_log_id IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True, default=utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    ad_account_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("ad_accounts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # What it is about: a group, or one advert of it.
    level: Mapped[str] = mapped_column(String(16), nullable=False, default="adset")
    external_id: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    adset_external_id: Mapped[str] = mapped_column(
        String(128), nullable=False, default=""
    )
    campaign_external_id: Mapped[str] = mapped_column(
        String(128), nullable=False, default=""
    )
    name: Mapped[str] = mapped_column(Text, nullable=False, default="")
    # ``core.agent.guard``'s kind, action and advised button.
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    action: Mapped[str] = mapped_column(String(8), nullable=False, default="warn")
    advice: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    step: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    said_step: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    # The price in usual prices, in hundredths.
    times: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    result_kind: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="")
    # The figures the message is written from, as they were at this step.
    figures: Mapped[Any] = mapped_column(Json, nullable=False, default=dict)
    baseline: Mapped[Any] = mapped_column(Json, nullable=False, default=dict)
    action_log_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    telegram_sent_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    telegram_message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    answer: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    answered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # The change the owner's answer opened at the provider.
    answer_log_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    # An answer given on figures over half an hour old waits for a second
    # look: ``checking`` while today's figures are read again, ``confirm``
    # while the owner is asked whether it is still wanted.
    pending_answer: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    pending_state: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    pending_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    now_figures: Mapped[Any] = mapped_column(Json, nullable=False, default=dict)
    # Whether the latest change landed: ``applied`` or ``failed``.
    result: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    result_text: Mapped[str] = mapped_column(Text, nullable=False, default="")
    owner: Mapped["User"] = relationship(foreign_keys=[owner_id], lazy="select")  # noqa: F821
    ad_account: Mapped["AdAccount"] = relationship(foreign_keys=[ad_account_id], lazy="select")  # noqa: F821
