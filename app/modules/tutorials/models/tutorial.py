from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, String, Text, Uuid
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.common.db import Base, utcnow
from app.modules.tutorials.constants import TutorialLanguage

# The parts written once per language. Uzbek has the plain columns (every
# lesson before languages was Uzbek); the others end in ``_ru`` / ``_en``.
LANGUAGE_PARTS = ("title", "description", "image", "video_url", "video_file")


def column(part: str, language: str) -> str:
    """The column holding one part of one language."""
    return part if language == TutorialLanguage.UZ else f"{part}_{language}"


class Tutorial(Base):
    """A video lesson in one to three languages. Each language written has a
    title and a video - ``video_url`` or ``video_file``, never both."""

    __tablename__ = "tutorials"
    __table_args__ = (Index("tutorials_active_created_idx", "is_active", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utcnow, onupdate=utcnow)
    type: Mapped[str] = mapped_column(String(16), nullable=False, default="meta")
    # The cabinet screens that show it beside their work (TutorialPlace).
    places: Mapped[list[str]] = mapped_column(ARRAY(String(32)), nullable=False, default=list)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_by_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    # Uzbek.
    title: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    image: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    video_url: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    video_file: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    # Russian.
    title_ru: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    description_ru: Mapped[str] = mapped_column(Text, nullable=False, default="")
    image_ru: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    video_url_ru: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    video_file_ru: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    # English.
    title_en: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    description_en: Mapped[str] = mapped_column(Text, nullable=False, default="")
    image_en: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    video_url_en: Mapped[str] = mapped_column(String(500), nullable=False, default="")
    video_file_en: Mapped[str] = mapped_column(String(255), nullable=False, default="")

    def part(self, part: str, language: str) -> str:
        return getattr(self, column(part, language)) or ""

    def set_part(self, part: str, language: str, value: str) -> None:
        setattr(self, column(part, language), value)

    @property
    def languages(self) -> list[str]:
        """The languages written, in the fallback order."""
        return [
            language
            for language in TutorialLanguage.values
            if self.part("title", language)
        ]

    def language_for(self, wanted: str) -> str:
        """The language a reader of ``wanted`` sees: theirs when written,
        else the first written in uz, ru, en."""
        written = self.languages
        if wanted in written:
            return wanted
        return written[0] if written else TutorialLanguage.UZ

    def file_for(self, part: str, language: str) -> tuple[str, str]:
        """``(language, name)`` of the image or the video file to show for a
        language: its own, else the first other language's that has one."""
        for candidate in (language, *TutorialLanguage.values):
            if name := self.part(part, candidate):
                return candidate, name
        return language, ""

    def files(self) -> list[str]:
        return [
            name
            for language in TutorialLanguage.values
            for part in ("image", "video_file")
            if (name := self.part(part, language))
        ]
