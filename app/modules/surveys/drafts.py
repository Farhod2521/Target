"""What the office typed, as the services take it: plain values in the source
language only. The router has checked them already."""

import uuid
from dataclasses import dataclass
from datetime import datetime

from app.modules.surveys.constants import ASK_AFTER_DAYS, QuestionKind, SurveyAudience


@dataclass(frozen=True, slots=True)
class QuestionDraft:
    """One question as written. `show_if` is the earlier choice question it
    hangs on, by position from one, and 0 for always asked."""

    kind: QuestionKind
    text: str
    options: tuple[str, ...] = ()
    allows_many: bool = False
    min_value: int | None = None
    max_value: int | None = None
    is_required: bool = True
    show_if: int = 0
    show_options: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class AudienceDraft:
    kind: SurveyAudience = SurveyAudience.EVERYONE
    plans: tuple[uuid.UUID, ...] = ()
    people: tuple[uuid.UUID, ...] = ()


@dataclass(frozen=True, slots=True)
class SurveyDraft:
    name: str
    source_language: str
    title: str
    intro: str
    questions: tuple[QuestionDraft, ...]
    audience: AudienceDraft = AudienceDraft()
    starts_at: datetime | None = None
    ends_at: datetime | None = None
    ask_after_days: int = ASK_AFTER_DAYS


@dataclass(frozen=True, slots=True)
class QuestionWording:
    text: str
    options: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class LanguageWording:
    title: str
    intro: str
    questions: tuple[QuestionWording, ...]
