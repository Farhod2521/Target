from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.common.db import Base, utcnow


class OfficeAdCampaign(Base):
    """A campaign of the office's own ad account whose spend the dashboard's
    advertising figures count. The superuser picks them; a campaign not
    here is not counted, even when it ran."""

    __tablename__ = "office_ad_campaigns"

    campaign_external_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    picked_by_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utcnow
    )
