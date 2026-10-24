"""The gate, which is the whole of "chat does not invent figures"."""

import pytest

from core.chat.context import (
    AccountDigest,
    BusinessDigest,
    ChatContext,
    TotalsDigest,
)
from core.chat.rungs import ResultDigest
from core.chat.verify import MARKER, FigureGate


def gate(*allowed: str, quoted: tuple[str, ...] = ()) -> FigureGate:
    return FigureGate(allowed=frozenset(allowed), quoted=frozenset(quoted))


def run(item: FigureGate, *chunks: str) -> str:
    return "".join([*(item.feed(chunk) for chunk in chunks), item.flush()])


def test_a_figure_from_the_context_passes() -> None:
    assert run(gate("15000"), "Sarf 15 000 so'm.") == "Sarf 15 000 so'm."


def test_a_figure_from_nowhere_never_reaches_the_screen() -> None:
    item = gate("15000")

    assert run(item, "Sarf 99 000 so'm.") == f"Sarf {MARKER} so'm."
    assert item.masked == 1


def test_a_figure_split_across_chunks_is_judged_whole() -> None:
    """The reason the gate is stateful.

    "15" arriving at the end of one piece becomes "15 000" at the start of
    the next. A gate that judged each piece would mask a number that was
    never wrong, which is the failure nobody would ever find.
    """
    assert run(gate("15000"), "CPL 15 ", "000 so'm") == "CPL 15 000 so'm"


def test_a_small_number_is_language_rather_than_measurement() -> None:
    """ "3 kun" is advice. Masking it would break every ordinary sentence."""
    assert run(gate(), "Bir-ikki kun, 3 kun kuting.") == "Bir-ikki kun, 3 kun kuting."


def test_the_length_of_a_shot_is_language_rather_than_measurement() -> None:
    """A video plan counts seconds, and a range of them with the long dash
    the house style asks for. Neither is a figure of the account."""
    text = "Video 15–30 soniya, birinchi 0–3 soniya, 25-34 yosh."

    assert run(gate(), text) == text


def test_a_percentage_is_checked_whatever_its_size() -> None:
    """A share is a claim about this account even when it is under a hundred."""
    item = gate()

    assert run(item, "Narx 25% oshdi.") == f"Narx {MARKER} oshdi."
    assert item.masked == 1


def test_a_percentage_from_the_context_passes() -> None:
    assert run(gate("25"), "Narx 25% oshdi.") == "Narx 25% oshdi."


def test_a_figure_the_person_typed_is_not_a_claim_about_them() -> None:
    assert run(gate(quoted=("50000",)), "Siz 50 000 dedingiz") == "Siz 50 000 dedingiz"


def test_the_allowed_set_comes_from_the_rendered_context() -> None:
    """The one property that keeps the two sides from drifting apart.

    ``figures`` is not collected while the digest is assembled - it is read
    back out of the very string that goes to the model. A separately built
    set would be a second source of truth, and the first time they
    disagreed the gate would mask a real figure or pass an invented one.
    """
    context = ChatContext(
        account=AccountDigest(
            business=BusinessDigest(
                name="Kafe", category="restaurant", offer="Tushlik", currency="UZS"
            ),
            totals=TotalsDigest(
                window_days=30,
                spend="1 200 000 UZS",
                results=(ResultDigest(kind="lead", count=42, cost="28 571 UZS"),),
            ),
            maturity="",
        )
    )

    assert {"1200000", "28571", "42", "30"} <= context.figures()
    assert run(gate(*context.figures()), "CPL 28 571 UZS.") == "CPL 28 571 UZS."


# --- a small figure is a claim when it is attached to one -----------------
def test_a_small_price_is_checked_like_any_other() -> None:
    """Dollar prices are small. "3 USD" passed as a word of the sentence."""
    item = gate()

    assert run(item, "Narxi 3 USD bo'ldi.") == f"Narxi {MARKER} USD bo'ldi."
    assert item.masked == 1


def test_a_fraction_of_a_dollar_is_checked() -> None:
    assert run(gate(), "Narx 0,25 USD.") == f"Narx {MARKER} USD."
    assert run(gate("025"), "Narx 0,25 USD.") == "Narx 0,25 USD."


def test_a_small_count_of_results_is_checked() -> None:
    assert run(gate(), "Kecha 7 ta murojaat keldi.") == (
        f"Kecha {MARKER} ta murojaat keldi."
    )
    assert run(gate("7"), "Kecha 7 ta murojaat keldi.") == "Kecha 7 ta murojaat keldi."


def test_a_count_of_ordinary_things_is_language() -> None:
    assert run(gate(), "2-3 ta rasm qo'shing.") == "2-3 ta rasm qo'shing."


def test_an_age_or_a_stretch_of_time_is_language() -> None:
    text = "25 yoshdan 45 yoshgacha, 14 kun kuting."
    assert run(gate(), text) == text


def test_a_number_attached_to_nothing_passes_only_up_to_ten() -> None:
    assert run(gate(), "Top 5 reklama.") == "Top 5 reklama."
    assert run(gate(), "Guruhda 45 bor.") == f"Guruhda {MARKER} bor."


def test_a_price_split_from_its_currency_is_still_held_for_it() -> None:
    """The piece ends in the middle of the word that makes it a claim."""
    assert run(gate(), "Narxi 3 US", "D bo'ldi.") == f"Narxi {MARKER} USD bo'ldi."
    assert run(gate(), "Kecha 7 ta mur", "ojaat keldi.") == (
        f"Kecha {MARKER} ta murojaat keldi."
    )


def test_a_share_written_as_a_word_is_checked_like_the_sign() -> None:
    """ "5 foiz" and "5%" say the same thing; only one of them used to be
    held for it, and a share is a claim at any size."""
    assert run(gate(), "Narx 5 foiz arzonlashdi.") == (
        f"Narx {MARKER} foiz arzonlashdi."
    )
    assert run(gate(), "Конверсия 5 процентов.") == f"Конверсия {MARKER} процентов."
    assert run(gate("5"), "Narx 5 foiz arzonlashdi.") == "Narx 5 foiz arzonlashdi."


def test_a_scale_word_makes_a_small_number_a_large_claim() -> None:
    """Eight in the text, eight million in the account.

    Read as a bare eight it passed for language, and the sentence around
    it was a statement about somebody's money out by six orders of
    magnitude - the largest wrong figure this gate can let through.
    """
    assert run(gate(), "Kecha 8 million so'm ketdi.") == (
        f"Kecha {MARKER} million so'm ketdi."
    )
    assert run(gate(), "Byudjet 3 ming so'm.") == f"Byudjet {MARKER} ming so'm."
    assert run(gate("8"), "Kecha 8 million so'm ketdi.") == (
        "Kecha 8 million so'm ketdi."
    )


@pytest.mark.parametrize(
    "text",
    [
        "Narxi 3 dollar bo'ldi.",
        "Har lid 2 dollardan tushdi.",
        "Narx 4 евро.",
        "Цена 3 доллара за заявку.",
        "Ушло 5 миллионов сум.",
        "Ушло 5 тыс. сум.",
        "Har murojaat 9 so'mga tushdi.",
        "Kecha 7 sumdan oshdi.",
        "Нарх 6 сўм.",
    ],
)
def test_a_currency_written_as_a_word_is_checked(text: str) -> None:
    """The word for the money, in any of the three languages, makes a
    small number a price - "3 dollar" passed as language."""
    item = gate()

    run(item, text)

    assert item.masked == 1


def test_a_word_that_only_starts_like_a_currency_is_language() -> None:
    text = "3 summary, 5 some."
    assert run(gate(), text) == text


def test_a_comparison_is_a_claim_about_the_account() -> None:
    """ "2 barobar qimmat" is a measurement of two weeks, not a word."""
    assert run(gate(), "Lid 2 barobar qimmat.") == f"Lid {MARKER} barobar qimmat."
    assert run(gate("2"), "Lid 2 barobar qimmat.") == "Lid 2 barobar qimmat."


def test_a_scale_word_split_across_chunks_is_still_held_for_it() -> None:
    """The piece ends inside the word that makes the number a claim."""
    assert run(gate(), "Kecha 8 mill", "ion so'm ketdi.") == (
        f"Kecha {MARKER} million so'm ketdi."
    )


@pytest.mark.parametrize("ratio", ["9:16", "16:9", "4:5"])
def test_a_screen_shape_is_not_a_figure(ratio: str) -> None:
    gate = FigureGate(allowed=frozenset())

    text = gate.feed(f"tik video ({ratio})") + gate.flush()

    assert text == f"tik video ({ratio})"
    assert gate.masked == 0


def test_a_ratio_split_across_pieces_is_judged_whole() -> None:
    gate = FigureGate(allowed=frozenset())

    text = "".join(gate.feed(piece) for piece in ["(9", ":", "1", "6)"]) + gate.flush()

    assert text == "(9:16)"


def test_a_range_split_across_pieces_keeps_its_unit() -> None:
    gate = FigureGate(allowed=frozenset())

    pieces = ["15\u2013", "20 soniya"]

    text = "".join(gate.feed(piece) for piece in pieces) + gate.flush()

    assert text == "15\u201320 soniya"


def test_a_time_of_day_is_still_a_figure() -> None:
    gate = FigureGate(allowed=frozenset())

    text = gate.feed("nisbat 9:45 bo'ldi") + gate.flush()

    assert text == f"nisbat 9:{MARKER} bo'ldi"


def test_a_price_written_with_its_sign_is_checked_too() -> None:
    """The screens now write dollars as "$3", and so will the answers."""
    item = gate()

    assert run(item, "Narxi $3 bo'ldi.") == f"Narxi ${MARKER} bo'ldi."
    assert item.masked == 1
    assert run(gate("025"), "Narx $0,25.") == "Narx $0,25."


def test_a_visitor_may_be_told_how_many_people_an_audience_needs() -> None:
    item = FigureGate(allowed=frozenset(), people_below=10**12)

    assert (
        run(item, "Kamida 500 000 kishilik hudud.") == "Kamida 500 000 kishilik hudud."
    )
    assert run(item, "1 million odam yetarli.") == "1 million odam yetarli."


def test_a_visitor_is_still_never_quoted_a_price() -> None:
    item = FigureGate(allowed=frozenset(), people_below=10**12)

    assert (
        run(item, "Lid narxi 15 000 so'm bo'ladi.")
        == f"Lid narxi {MARKER} so'm bo'ladi."
    )


def test_an_account_head_count_is_checked_like_any_figure() -> None:
    assert (
        run(gate(), "Auditoriyangiz 500 000 kishi.")
        == f"Auditoriyangiz {MARKER} kishi."
    )
