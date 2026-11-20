"""The language and script a person wrote in, and the reply that follows it."""

import pytest

from core.written import (
    ENGLISH,
    RUSSIAN,
    UZBEK,
    UZBEK_LATIN,
    Written,
    reply_language,
    written_in,
    written_or,
)

UZ_CYRILLIC = Written(UZBEK, cyrillic=True)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Parolimni esdan chiqardim nima qilsam bo'ladi?", UZBEK_LATIN),
        ("Parolimni esdan chiqardim nima qilsam boʻladi?", UZBEK_LATIN),
        ("Reklama narxi qancha", UZBEK_LATIN),
        ("Biz Toshkentda kiyim sotamiz, yetkazib berish bor", UZBEK_LATIN),
        ("Паролимни эсдан чиқардим нима қилсам бўлади?", UZ_CYRILLIC),
        # Typed on a Russian keyboard: no ў қ ғ ҳ, still Uzbek.
        ("Паролимни эсдан чикардим нима килсам булади?", UZ_CYRILLIC),
        ("Биз Тошкентда кийим сотамиз, етказиб бериш бор", UZ_CYRILLIC),
        ("Я забыл пароль, что делать?", Written(RUSSIAN)),
        ("Мы продаём одежду в Ташкенте, доставка бесплатно", Written(RUSSIAN)),
        ("Курсы английского языка для детей", Written(RUSSIAN)),
        ("kak sdelat reklamu", Written(RUSSIAN)),
        ("I forgot my password, what should I do?", Written(ENGLISH)),
    ],
)
def test_written_in(text: str, expected: Written) -> None:
    assert written_in(text) == expected


@pytest.mark.parametrize(
    "text", ["ok", "", "https://x.uz", "+998 90 123 45 67", "Ресторан"]
)
def test_too_little_says_nothing(text: str) -> None:
    assert written_in(text) is None


def test_names_tell_the_script() -> None:
    assert UZBEK_LATIN.name == "Uzbek, in the Latin script"
    assert UZ_CYRILLIC.name == "Uzbek, in the Cyrillic script"
    assert Written(RUSSIAN).name == "Russian"
    assert UZ_CYRILLIC.key == "uz-cyrl"
    assert UZBEK_LATIN.key == "uz"


def test_the_question_beats_the_page() -> None:
    # The screenshot: an Uzbek page answered in Russian.
    asked = "Parolimni esdan chiqardim nima qilsam bo'ladi?"
    assert reply_language(asked, (), "ru", "ru") == UZBEK_LATIN
    assert reply_language("Я забыл пароль", (), "uz") == Written(RUSSIAN)


def test_a_short_question_follows_earlier_words_then_the_page() -> None:
    earlier = ("Паролимни эсдан чиқардим",)
    assert reply_language("ok", earlier, "ru") == UZ_CYRILLIC
    assert reply_language("ok", (), "ru", "uz") == Written(RUSSIAN)
    assert reply_language("ok", (), "", "en") == Written(ENGLISH)
    assert reply_language("ok") == UZBEK_LATIN


def test_written_or_falls_back_on_the_code() -> None:
    assert written_or("ru", "ok") == Written(RUSSIAN)
    assert written_or("xx", "") == UZBEK_LATIN


@pytest.mark.parametrize(
    ("latin", "cyrillic"),
    [
        ("Sozlash → Obuna va to'lov", "Созлаш → Обуна ва тўлов"),
        ("Qo'ng'iroq qilish", "Қўнғироқ қилиш"),
        ("Telegram'da yozish", "Telegram'да ёзиш"),
        ("CRM va Lidlar", "CRM ва Лидлар"),
        ("Eng yaxshi", "Энг яхши"),
        ("Ma'lumotlarni ko'ryapman…", "Маълумотларни кўряпман…"),
    ],
)
def test_to_cyrillic(latin: str, cyrillic: str) -> None:
    from core.written import to_cyrillic

    assert to_cyrillic(latin) == cyrillic
