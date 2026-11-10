from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from app.common.db import Base, utcnow


class SignupSheetRow(Base):
    """A sign-up already written to the team's sheet of those who did not pay.

    One row per account, so nobody is written twice. Paying later changes
    nothing here or in the sheet.
    """

    __tablename__ = "signup_sheet_rows"

    owner_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    written_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
