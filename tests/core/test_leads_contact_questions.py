"""A typed question asking for a name, a phone or an email.

Meta's review rejected an advert whose form asked "Ismingiz" and "Telefon
raqamingiz" as questions of the advertiser's own. These are the labels that
must be caught, and the ones that look close and must not.
"""

import pytest

from core.leads import contact_kind


@pytest.mark.parametrize(
    ("label", "kind"),
    [
        ("Ismingiz", "full_name"),
        ("Ism va familiyangiz", "full_name"),
        ("F.I.O.", "full_name"),
        ("Ваше имя", "full_name"),
        ("Your name", "full_name"),
        ("Telefon raqamingiz", "phone"),
        ("Raqamingiz", "phone"),
        ("Aloqa raqami", "phone"),
        ("Tel", "phone"),
        ("Номер телефона", "phone"),
        ("Phone number", "phone"),
        ("Ismingiz va telefon raqamingiz", "phone"),
        ("Email manzilingiz", "email"),
        ("E-mail", "email"),
        ("Электронная почта", "email"),
    ],
)
def test_a_contact_question_is_recognised(label: str, kind: str) -> None:
    assert contact_kind(label) == kind


@pytest.mark.parametrize(
    "label",
    [
        "Qaysi kurs qiziq?",
        "Kurs nomi",
        "Darslarimiz Toshkent shahrida. Siz Toshkentda yashaysizmi?",
        # "Raqam" in a long question is as likely to be a document.
        "Pasport seriyasi va raqamingiz qanday?",
        "Pochta indeksingiz",
        "Telegram username",
        "Почти готовы?",
        "",
    ],
)
def test_a_question_that_only_looks_close_is_left_alone(label: str) -> None:
    assert contact_kind(label) is None
