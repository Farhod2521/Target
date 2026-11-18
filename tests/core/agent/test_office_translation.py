"""A translated office text is used only when it is the same text."""

import pytest

from core.agent.office_translation import (
    OfficeTranslation,
    TranslatedField,
    TranslatedLanguage,
    TranslationMismatchError,
    checked,
)

SOURCE = {
    "answer": (
        "Akkauntda **to'lov usuli yo'q**.\n\n"
        "1. To'lov sahifasini oching: [[tolov]]\n"
        "2. Kartani qo'shing.\n\n"
        "- Karta xalqaro bo'lsin."
    )
}
RU = (
    "В аккаунте **нет способа оплаты**.\n\n"
    "1. Откройте страницу оплаты: [[tolov]]\n"
    "2. Добавьте карту.\n\n"
    "- Карта должна быть международной."
)


def _answer(**texts: str) -> OfficeTranslation:
    return OfficeTranslation(
        languages=[
            TranslatedLanguage(
                language=code, fields=[TranslatedField(name="answer", text=text)]
            )
            for code, text in texts.items()
        ]
    )


def test_the_same_text_in_every_language_is_taken() -> None:
    found = checked(_answer(ru=RU, en=RU), languages=["ru", "en"], source=SOURCE)

    assert found["ru"]["answer"] == RU and set(found) == {"ru", "en"}


@pytest.mark.parametrize(
    "broken",
    [
        RU.replace("[[tolov]]", "[[оплата]]"),
        RU.replace("[[tolov]]", ""),
        RU.replace("2. Добавьте карту.\n", ""),
        RU.replace("- Карта", "Карта"),
        "  ",
    ],
)
def test_a_lost_link_step_or_list_line_refuses_the_whole(broken: str) -> None:
    with pytest.raises(TranslationMismatchError):
        checked(_answer(ru=broken), languages=["ru"], source=SOURCE)


def test_a_missing_or_unasked_language_or_field_is_refused() -> None:
    with pytest.raises(TranslationMismatchError):
        checked(_answer(ru=RU), languages=["ru", "en"], source=SOURCE)
    with pytest.raises(TranslationMismatchError):
        checked(_answer(ru=RU, uz=RU), languages=["ru"], source=SOURCE)
    with pytest.raises(TranslationMismatchError):
        checked(_answer(ru=RU), languages=["ru"], source={**SOURCE, "problem": "Karta"})
