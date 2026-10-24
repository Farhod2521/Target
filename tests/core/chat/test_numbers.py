"""The tokeniser both sides of the gate share."""

from core.chat.numbers import canonical, figures_in


def test_thousands_separators_do_not_change_the_amount() -> None:
    """The same money in three locales has to match itself.

    Uzbek and Russian split thousands with a space, English with a comma.
    A gate that compared the rendered strings would mask a real figure the
    moment somebody switched language.
    """
    assert canonical("15 000") == canonical("15,000") == "15000"


def test_a_full_stop_ending_a_sentence_is_not_part_of_the_figure() -> None:
    assert figures_in("Sarf 15 000 so'm.") == {"15000"}


def test_a_comma_separated_list_is_three_figures_not_one() -> None:
    assert figures_in("1, 2, 3") == {"1", "2", "3"}


def test_a_year_is_read_whole() -> None:
    """A grouping pattern that split 2026 into 202 and 6 would mask dates."""
    assert "2026" in figures_in("2026-08-26")
