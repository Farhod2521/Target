"""The word check on advert copy, held to the adverts that actually ran.

Every case with a business name is taken from a launch trace: the owner's
text as they typed it, the words that reached the advert, and the button
the goal put under them. The check passing one of them is a regression in
the one place that was meant to stop it.
"""

from core.agent.copy_check import (
    AdWords,
    check_against_offer,
    check_words,
)
from core.agent.copy_words import normalize

HIKMAT_OFFER = (
    "Сентябрь ойи учун: 17, 19, 24 ва 26\n"
    "ХИКМАТ УМРА ТРАВЕЛНИНГ ( 10 КУНДИЗ) (LUXE) ПАКЕТИ\n"  # noqa: RUF001
    "5 кун Мадинада 4 Ҳарамдан 2 дақиқалик масофада.\n"
    "5 кун Маккада 5 Ҳарамдан 5 дақиқалик масофада.\n"
    "Мурожаат учун 71 205 5050"
)


def codes(words: AdWords, *, facts: str, sends_to: str) -> set[str]:
    return {
        finding.code
        for finding in check_against_offer(words=words, facts=facts, sends_to=sends_to)
    }


def test_cyrillic_and_latin_are_compared_in_one_spelling() -> None:
    assert normalize("Мадинада Ўзбекистон Ғалаба") == "madinada o'zbekiston g'alaba"
    assert normalize("Oʻzbekiston  bo‘ylab") == "o'zbekiston bo'ylab"  # noqa: RUF001


def test_a_form_advert_that_tells_people_to_call_is_caught() -> None:
    """Hikmat Travel, a lead goal: the owner's own "call us" copied under a
    button that opens a form."""
    words = AdWords(
        primary_text=(
            "Umraga ishonchli safarni o'zingiz izlab charchadingizmi? Hikmat "
            "Travel Luxe 10 kunlik paketida 4-5 yulduzli mehmonxonalar. "
            "Batafsil ma'lumot uchun qo'ng'iroq qiling."
        ),
        headline="10 kunlik Umra safari - Lyuks paket",
        description="Harom yaqinida mehmonxonalar",
    )

    assert codes(words, facts=HIKMAT_OFFER, sends_to="form") == {"action_mismatch"}


def test_a_fact_bent_out_of_the_same_digits_is_left_to_the_second_read() -> None:
    """Hikmat Travel: "5 kun Madinada" became "10 kun Madina". Every digit is
    in the offer, so no word list sees it - which is exactly why an offer
    with numbers is always read a second time."""
    words = AdWords(
        primary_text=(
            "Umra safarini tashkil qilish tashvishidan xalos bo'ling. Madina va "
            "Makkada 4-5 yulduzli mehmonxonalar. Batafsil ma'lumot uchun xabar "
            "yozing."
        ),
        headline="Umra Luxe paketi - Sentyabr sayohati",
        description="10 kun Madina, 10 kun Makka: parvoz va viza narxga kiritilgan.",
    )

    assert codes(words, facts=HIKMAT_OFFER, sends_to="chat") == set()


def test_a_clinic_advert_about_the_readers_hair_and_a_free_visit_is_caught() -> None:
    """The hair clinic: a question about the reader's hair loss, and a free
    consultation the owner never offered."""
    offer = (
        "Resublikada eng taniqli bo'lgan Akfamedline klinikasida soch ektirish "
        "siz o'ylaganingizdan ancha arzon! Raqamlaringizni qoldirib ma'lumot oling"
    )
    words = AdWords(
        primary_text=(
            "Soch to'kilishi ko'plab erkaklarni bezovta qiladi. Akfamedline "
            "klinikasida zamonaviy soch ektirish xizmati mavjud. Ariza "
            "qoldiring, mutaxassis siz bilan bog'lanadi."
        ),
        headline="Soch to'kilishidan charchadingizmi?",
        description="Akfamedline klinikasida bepul maslahat oling.",
    )

    assert codes(words, facts=offer, sends_to="form") == {
        "promise_not_in_offer",
        "personal_attribute",
    }


def test_a_promise_the_owner_made_is_not_flagged() -> None:
    """Step12 wrote "bepul diagnostika" itself."""
    offer = "Bepul diagnostikada darajangizni tahlil qilib beramiz."
    words = AdWords(
        primary_text="Bepul diagnostikada aniq darajangizni bilib oling va boshlang.",
        headline="SAT kursiga nabor ochildi",
        description="Jonli darslar va mock testlar",
    )

    assert codes(words, facts=offer, sends_to="website") == set()


def test_ordering_under_a_form_button_is_caught() -> None:
    """Aziz market: "buyurtma bering" above a sign-up form."""
    offer = (
        "BATANA OIL — SOQOL PARVARISHI UCHUN!\n"
        "Pipetkali idish — 30 ml\n"
        "Mahsulot narxi 79.000"
    )
    words = AdWords(
        primary_text=(
            "Batana Oil tabiiy yog'lari soqol va terini yumshatadi. Hoziroq "
            "buyurtma bering va farqni his qiling."
        ),
        headline="Soqol uchun tabiiy yog' - Batana Oil",
        description="30 ml pipetkali idish - 79 000 so'm.",
    )

    assert codes(words, facts=offer, sends_to="form") == {"action_mismatch"}


def test_two_words_in_every_field_is_caught_whoever_typed_them() -> None:
    """Shohjahon: three live adverts said "Ariza qoldiring" and nothing else."""
    words = AdWords(
        primary_text="Ariza qoldiring",
        headline="Ariza qoldiring",
        description="Ariza qoldiring",
    )

    assert {finding.code for finding in check_words(words=words)} == {
        "too_short",
        "same_in_all_fields",
    }


def test_empty_words_are_their_own_finding() -> None:
    words = AdWords(primary_text="  ", headline="Tushlik", description="")

    assert [finding.code for finding in check_words(words=words)] == ["empty"]


def test_a_phone_number_the_owner_gave_a_website_advert_must_keep() -> None:
    """Killerplus, a traffic goal: the number was in the offer twice and in
    the advert not at all."""
    offer = "Killer Plus 55gramlik geli\nO'zbekiston bo'ylab dastavka bor\n94 015 86 86"
    words = AdWords(
        primary_text=(
            "Killer Plus geli 55 gramda. O'zbekiston bo'ylab yetkazib berish "
            "bor, saytga kirib buyurtma bering."
        ),
        headline="Tarakanlardan tinchgina qutuling",
        description="Butun O'zbekiston bo'ylab yetkaziladi.",
    )

    found = check_against_offer(words=words, facts=offer, sends_to="website")

    assert [(finding.code, finding.detail) for finding in found] == [
        ("phone_dropped", "940158686")
    ]


def test_a_phone_number_on_a_form_advert_is_caught() -> None:
    offer = "Ish tushligi 25 000 so'mdan. Tel: 90 123 45 67"
    words = AdWords(
        primary_text="Ish tushligi 25 000 so'mdan. Ariza qoldiring yoki 90 123 45 67.",
        headline="Tushlik",
        description="Chilonzorda",
    )

    assert codes(words, facts=offer, sends_to="form") == {"phone_in_form_ad"}


def test_an_invented_discount_is_caught_as_a_number_and_a_promise() -> None:
    offer = "Chilonzorda kichik kafe. Ish tushligi 25 000 so'mdan."
    words = AdWords(
        primary_text="Bugun ish tushligiga 30% chegirma. Ariza qoldiring.",
        headline="Tushlik",
        description="Chilonzorda",
    )

    found = check_against_offer(words=words, facts=offer, sends_to="form")

    assert {(finding.code, finding.detail) for finding in found} == {
        ("number_not_in_offer", "30"),
        ("promise_not_in_offer", "chegirma"),
    }


def test_an_amount_written_two_ways_is_one_amount_and_not_a_phone() -> None:
    offer = "Kurs narxi 1.500.000 so'm, darslar har kuni."
    words = AdWords(
        primary_text="Kurs narxi 1 500 000 so'm, darslar har kuni. Ariza qoldiring.",
        headline="Har kuni darslar",
        description="Toshkentda",
    )

    assert codes(words, facts=offer, sends_to="website") == set()


def test_a_call_the_form_promises_is_not_a_request_to_call() -> None:
    offer = "Soch ektirish xizmati."
    words = AdWords(
        primary_text=(
            "Soch ektirish xizmati. Ariza qoldiring, mutaxassis qo'ng'iroq qiladi."
        ),
        headline="Soch ektirish",
        description="Klinikada",
    )

    assert codes(words, facts=offer, sends_to="form") == set()
