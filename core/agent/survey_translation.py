"""A survey's wording translated into the other languages, and its check."""

from collections.abc import Sequence

from pydantic import BaseModel, Field


class TranslatedQuestion(BaseModel):
    """One question in one language. ``options`` only for a choice."""

    text: str = Field(description="The question, translated.")
    options: list[str] = Field(
        default_factory=list,
        description="The choice's options in the same order; empty otherwise.",
    )


class SurveyLanguage(BaseModel):
    """The whole survey in one target language."""

    language: str = Field(description="The language code, exactly as given.")
    title: str
    intro: str = Field(default="", description="Empty when the source is empty.")
    questions: list[TranslatedQuestion]


class SurveyTranslation(BaseModel):
    """Every target language, each once."""

    languages: list[SurveyLanguage]


class TranslationMismatchError(Exception):
    """The answer is not the same survey as the one sent."""


def checked(
    answer: SurveyTranslation,
    *,
    languages: Sequence[str],
    option_counts: Sequence[int],
    has_intro: bool,
) -> dict[str, SurveyLanguage]:
    """Each target language's wording, or ``TranslationMismatchError``."""
    found: dict[str, SurveyLanguage] = {}
    for item in answer.languages:
        if item.language in found or item.language not in languages:
            raise TranslationMismatchError(f"unexpected language {item.language!r}")
        found[item.language] = item
    if set(found) != set(languages):
        raise TranslationMismatchError("a language is missing")
    for item in found.values():
        _check_one(item, option_counts=option_counts, has_intro=has_intro)
    return found


def _check_one(
    item: SurveyLanguage, *, option_counts: Sequence[int], has_intro: bool
) -> None:
    if not item.title.strip():
        raise TranslationMismatchError(f"{item.language}: empty title")
    if has_intro and not item.intro.strip():
        raise TranslationMismatchError(f"{item.language}: empty intro")
    if len(item.questions) != len(option_counts):
        raise TranslationMismatchError(f"{item.language}: question count differs")
    for question, count in zip(item.questions, option_counts, strict=True):
        if not question.text.strip():
            raise TranslationMismatchError(f"{item.language}: empty question")
        options = [option for option in question.options if option.strip()]
        if len(options) != count or len(question.options) != count:
            raise TranslationMismatchError(f"{item.language}: option count differs")
