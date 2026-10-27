from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Index, SmallInteger, String, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.db import Base, Json, utcnow


class _Tenant:
    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    owner_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True)


class CrmStage(_Tenant, Base):
    __tablename__ = "crm_stages"
    __table_args__ = (Index("crm_stages_owner_position_idx", "owner_id", "position"),)

    name: Mapped[str] = mapped_column(String(48), nullable=False, default="")
    color: Mapped[str] = mapped_column(String(7), nullable=False, default="")
    kind: Mapped[str] = mapped_column(String(8), nullable=False, default="")
    position: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    counts_as_quality: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class CrmLostReason(_Tenant, Base):
    __tablename__ = "crm_lost_reasons"
    __table_args__ = (Index("crm_lost_reasons_owner_position_idx", "owner_id", "position"),)

    name: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    position: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)


class CrmCard(_Tenant, Base):
    __tablename__ = "crm_cards"
    __table_args__ = (
        Index("crm_cards_owner_stage_idx", "owner_id", "stage_id"),
        Index("crm_cards_owner_assignee_idx", "owner_id", "assignee_id"),
        Index("crm_cards_owner_due_idx", "owner_id", "due_at"),
        Index("crm_cards_owner_updated_idx", "owner_id", "updated_at"),
        Index("crm_cards_owner_qualified_idx", "owner_id", "qualified_at"),
    )

    lead_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("leads.id", ondelete="CASCADE"), nullable=False, unique=True)
    stage_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("crm_stages.id", ondelete="RESTRICT"), nullable=False, index=True)
    assignee_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    due_note: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    attempts: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    last_note: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    last_note_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    returned: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    qualified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    won_amount_minor: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="")
    lost_reason_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("crm_lost_reasons.id", ondelete="SET NULL"), nullable=True, index=True)
    lost_reason_name: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    taken_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    quality_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    lead: Mapped["Lead"] = relationship(foreign_keys=[lead_id], lazy="select")  # noqa: F821
    stage: Mapped["CrmStage"] = relationship(foreign_keys=[stage_id], lazy="select")
    assignee: Mapped["User | None"] = relationship(foreign_keys=[assignee_id], lazy="select")  # noqa: F821
    lost_reason: Mapped["CrmLostReason | None"] = relationship(foreign_keys=[lost_reason_id], lazy="select")


class CrmActivity(_Tenant, Base):
    __tablename__ = "crm_activities"
    __table_args__ = (Index("crm_activities_card_created_idx", "card_id", "created_at"),)

    card_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("crm_cards.id", ondelete="CASCADE"), nullable=False, index=True)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    kind: Mapped[str] = mapped_column(String(16), nullable=False, default="")
    text: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    actor: Mapped["User | None"] = relationship(foreign_keys=[actor_id], lazy="select")  # noqa: F821


class CrmMember(_Tenant, Base):
    __tablename__ = "crm_members"
    __table_args__ = (Index("crm_members_owner_active_idx", "owner_id", "is_active"),)

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, unique=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    takes_leads: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    must_change_password: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    kpi_fix_minor: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    kpi_percent: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    kpi_currency: Mapped[str] = mapped_column(String(3), nullable=False, default="")
    user: Mapped["User"] = relationship(foreign_keys=[user_id], lazy="select")  # noqa: F821

    @property
    def has_kpi(self) -> bool:
        return self.kpi_fix_minor is not None or self.kpi_percent is not None


class CrmSetup(_Tenant, Base):
    __tablename__ = "crm_setups"
    __table_args__ = (UniqueConstraint("owner_id", name="uniq_crm_setup_per_owner"),)

    state: Mapped[str] = mapped_column(String(8), nullable=False, default="draft")
    step: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    since: Mapped[str] = mapped_column(String(12), nullable=False, default="week")
    leads_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    every_ad: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    ad_external_ids: Mapped[Any] = mapped_column(Json, nullable=False, default=list)
    offered_ad_ids: Mapped[Any] = mapped_column(Json, nullable=False, default=list)
    take_new_ads: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    distribution: Mapped[str] = mapped_column(String(16), nullable=False, default="round_robin")
    last_assigned_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="")
    enabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # -- django extras --
    last_assigned: Mapped["User | None"] = relationship(foreign_keys=[last_assigned_id], lazy="select")  # noqa: F821
