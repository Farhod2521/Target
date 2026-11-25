from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.db import Base, Json, utcnow


class TestPayment(Base):
    """A real payment the superuser makes from the office to try a card.

    It pays for nothing: no invoice, no subscription. Its ``number`` is sent
    to Multicard as the ``invoice_id`` and starts with ``TEST-``, so the
    payment callback knows it from a bill.
    """

    __tablename__ = "test_payments"
    __test__ = False  # not a pytest class

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    number: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    actor_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)
    # ``card`` (the actor's saved card) or ``page`` (Multicard's checkout page).
    method: Mapped[str] = mapped_column(String(8), nullable=False)
    usd_cents: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # Whole so'm sent to Multicard, from ``usd_cents`` at ``rate``.
    amount_uzs: Mapped[int] = mapped_column(BigInteger, nullable=False)
    rate: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    rate_date: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="created")
    # The office test card it was taken from; null: the account's card or the page.
    card_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("test_cards.id", ondelete="SET NULL"), nullable=True)
    # Multicard's payment uuid; empty for a page until its callback comes.
    external_id: Mapped[str] = mapped_column(String(128), nullable=False, default="")
    page_url: Mapped[str] = mapped_column(String(512), nullable=False, default="")
    card_pan: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    card_ps: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    detail: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    refunded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    raw: Mapped[Any] = mapped_column(Json, nullable=False, default=dict)
    actor: Mapped["User"] = relationship(foreign_keys=[actor_id], lazy="select")  # noqa: F821, UP037
