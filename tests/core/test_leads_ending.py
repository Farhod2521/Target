"""The screen after a lead form: the Telegram spellings and the AI's rule."""

from pathlib import Path

import pytest

from core.leads.ending import (
    AI_ENDINGS,
    EndingLine,
    FormEnding,
    ai_ending_kind,
    ending_from_answer,
    line_of,
    provider_line,
    telegram_of,
    telegram_url,
    telegram_username,
)


@pytest.mark.parametrize(
    "typed",
    [
        "osh_markazi",
        "@osh_markazi",
        "t.me/osh_markazi",
        "https://t.me/osh_markazi",
        "https://t.me/osh_markazi/",
        "http://www.t.me/osh_markazi?start=1",
        "telegram.me/osh_markazi",
        "  @osh_markazi  ",
    ],
)
def test_every_spelling_of_a_username_is_the_same_username(typed: str) -> None:
    assert telegram_username(typed) == "osh_markazi"


@pytest.mark.parametrize(
    "typed",
    [
        "",
        "osh",  # shorter than Telegram allows
        "1osh_markazi",  # starts with a digit
        "osh markazi",
        "https://instagram.com/osh_markazi",
        "https://osh.uz/osh_markazi",
        "@",
    ],
)
def test_what_is_not_a_username_is_refused(typed: str) -> None:
    assert telegram_username(typed) == ""


def test_a_username_becomes_a_t_me_link() -> None:
    assert telegram_url("osh_markazi") == "https://t.me/osh_markazi"


def test_a_telegram_address_is_recognised_and_any_other_is_not() -> None:
    assert telegram_of("https://t.me/osh_markazi") == "osh_markazi"
    assert telegram_of("https://osh.uz") == ""


def test_the_twelve_categories_each_have_an_ending() -> None:
    assert len(AI_ENDINGS) == 12
    assert ai_ending_kind(category="medical") == "call"
    assert ai_ending_kind(category="ecommerce") == "website"


def test_no_category_gets_no_button() -> None:
    """A business that typed its own trade is passed in without one."""
    assert ai_ending_kind(category="") == "none"


def test_an_unknown_category_gets_no_button() -> None:
    assert ai_ending_kind(category="bakery") == "none"


def test_a_stored_answer_reads_back_whole() -> None:
    ending = FormEnding(
        kind="telegram", target="osh_markazi", button_text="Yozing", title="Rahmat"
    )

    assert ending_from_answer(ending.as_answer()) == ending


@pytest.mark.parametrize("stored", [None, "", {}, {"kind": "whatsapp"}, ["call"]])
def test_an_unreadable_answer_is_no_answer(stored: object) -> None:
    assert ending_from_answer(stored) is None


def test_the_button_words_default_by_kind() -> None:
    assert FormEnding(kind="call", target="+998901234567").words == "Qo'ng'iroq qilish"
    assert FormEnding(kind="call", button_text="Qo'ng'iroq").words == "Qo'ng'iroq"
    assert FormEnding(kind="none", button_text="x").words == ""


def test_the_table_names_exactly_the_catalogue_categories() -> None:
    """A category added to the catalogue without a row here gets no button;
    this says so in the test run rather than on a customer's phone."""
    catalogue = Path(__file__).resolve().parents[2] / "core" / "targeting" / "catalog"

    assert set(AI_ENDINGS) == {path.stem for path in catalogue.glob("*.yaml")}


def test_a_line_shows_targets_the_way_the_owner_writes_them() -> None:
    site = FormEnding(kind="website", target="https://www.osh.uz/")
    telegram = FormEnding(kind="telegram", target="osh_markazi", button_text="Yozing")

    assert line_of(site) == EndingLine(words="Saytga o'tish", target="osh.uz")
    assert line_of(telegram) == EndingLine(words="Yozing", target="@osh_markazi")
    assert line_of(FormEnding(kind="none")) == EndingLine()


def test_a_provider_link_to_telegram_reads_as_telegram() -> None:
    line = provider_line(
        kind="website", target="https://t.me/osh_markazi", button_text=""
    )

    assert line == EndingLine(words="Telegram'da yozish", target="@osh_markazi")


def test_a_button_we_do_not_build_is_shown_by_its_words() -> None:
    line = provider_line(kind="other", target="", button_text="Yuklab olish")

    assert line == EndingLine(words="Yuklab olish")


def test_a_provider_that_said_nothing_gives_no_line() -> None:
    assert provider_line(kind="", target="", button_text="") is None
