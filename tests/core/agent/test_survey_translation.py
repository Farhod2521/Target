"""The check a survey translation passes before it is written.

What is pinned: the same survey in every language passes; a missing or
repeated language, a dropped question or option, and an empty text are
each refused whole.
"""

import pytest

from core.agent.survey_translation import (
    SurveyLanguage,
    SurveyTranslation,
    TranslatedQuestion,
    TranslationMismatchError,
    checked,
)


def _language(code: str, **overrides: object) -> SurveyLanguage:
    fields: dict[str, object] = {
        "language": code,
        "title": "Title",
        "intro": "",
        "questions": [
            TranslatedQuestion(text="What got in the way?"),
            TranslatedQuestion(text="Which part?", options=["Ads", "Reports"]),
        ],
    }
    fields.update(overrides)
    return SurveyLanguage(**fields)  # type: ignore[arg-type]


def _check(
    *items: SurveyLanguage, has_intro: bool = False
) -> dict[str, SurveyLanguage]:
    return checked(
        SurveyTranslation(languages=list(items)),
        languages=("ru", "en"),
        option_counts=(0, 2),
        has_intro=has_intro,
    )


def test_the_same_survey_in_every_language_passes() -> None:
    found = _check(_language("ru"), _language("en"))

    assert set(found) == {"ru", "en"}


@pytest.mark.parametrize(
    "items",
    [
        (_language("ru"),),
        (_language("ru"), _language("ru")),
        (_language("ru"), _language("de")),
        (_language("ru"), _language("en", title=" ")),
        (
            _language("ru"),
            _language("en", questions=[TranslatedQuestion(text="Only one")]),
        ),
        (
            _language("ru"),
            _language(
                "en",
                questions=[
                    TranslatedQuestion(text="What?"),
                    TranslatedQuestion(text="Which?", options=["Ads"]),
                ],
            ),
        ),
        (
            _language("ru"),
            _language(
                "en",
                questions=[
                    TranslatedQuestion(text="What?"),
                    TranslatedQuestion(text="Which?", options=["Ads", ""]),
                ],
            ),
        ),
    ],
)
def test_a_different_survey_is_refused(items: tuple[SurveyLanguage, ...]) -> None:
    with pytest.raises(TranslationMismatchError):
        _check(*items)


def test_an_intro_the_source_has_must_be_translated() -> None:
    with pytest.raises(TranslationMismatchError):
        _check(_language("ru", intro="Intro"), _language("en"), has_intro=True)
