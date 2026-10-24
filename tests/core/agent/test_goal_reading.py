"""What the first screen may do with a reading of the owner's words.

The model proposes a goal; this decides what reaches the screen. No database:
the rules are about the answer and the catalogue's keys, nothing else.
"""

from core.agent import GoalIntent, read_goal

OFFERED = ("leads", "messages", "calls", "views", "traffic")
WORDS = "Mototsikl olmoqchi bo'lganlar telefon raqamini qoldirsin"


def intent(*goals: str, quote: str = "", wants_sale: bool = False) -> GoalIntent:
    return GoalIntent(goals=list(goals), quote=quote, wants_sale=wants_sale)


def test_one_goal_is_an_answer_with_the_words_it_rests_on() -> None:
    reading = read_goal(
        intent("leads", quote="telefon raqamini qoldirsin"), offered=OFFERED, text=WORDS
    )

    assert (reading.state, reading.goals, reading.quote) == (
        "found",
        ("leads",),
        "telefon raqamini qoldirsin",
    )


def test_two_results_are_a_question_not_an_answer() -> None:
    """One campaign works toward one result. Choosing is the owner's call."""
    reading = read_goal(intent("calls", "messages"), offered=OFFERED, text=WORDS)

    assert (reading.state, reading.goals) == ("two", ("calls", "messages"))


def test_a_goal_this_business_cannot_run_is_dropped() -> None:
    """A key off the list would tick a radio button that is not on the page."""
    reading = read_goal(intent("awareness"), offered=OFFERED, text=WORDS)

    assert (reading.state, reading.goals) == ("unclear", ())


def test_a_dropped_key_does_not_turn_a_single_answer_into_two() -> None:
    reading = read_goal(intent("leads", "awareness"), offered=OFFERED, text=WORDS)

    assert (reading.state, reading.goals) == ("found", ("leads",))


def test_the_same_key_twice_is_one_goal() -> None:
    reading = read_goal(intent("leads", "leads"), offered=OFFERED, text=WORDS)

    assert reading.state == "found"


def test_no_goal_is_unclear_rather_than_a_guess() -> None:
    reading = read_goal(intent(), offered=OFFERED, text="Moto bikes uchun reklama")

    assert (reading.state, reading.goals) == ("unclear", ())


def test_a_sale_is_offered_the_site_visit_by_name() -> None:
    """No goal on offer builds a sale; the nearest one that does is a visit."""
    reading = read_goal(intent(wants_sale=True), offered=OFFERED, text="sotib olsin")

    assert (reading.state, reading.goals) == ("sale", ("traffic",))


def test_a_sale_with_no_site_visit_on_offer_is_unclear() -> None:
    reading = read_goal(
        intent(wants_sale=True), offered=("leads", "calls"), text="sotib olsin"
    )

    assert reading.state == "unclear"


def test_a_quote_the_owner_did_not_write_is_not_shown() -> None:
    """It is shown in quotation marks as their words."""
    reading = read_goal(
        intent("leads", quote="ariza qoldirishsin"), offered=OFFERED, text=WORDS
    )

    assert reading.quote == ""


def test_a_quote_copied_with_another_apostrophe_is_still_theirs() -> None:
    """Uzbek writes o' four ways, and a faithful copy normalises it."""
    reading = read_goal(
        intent("calls", quote="qo'ng'iroq qilsin"),
        offered=OFFERED,
        text="Mijozlar menga qo\u2018ng\u2018iroq qilsin",
    )

    assert reading.quote == "qo'ng'iroq qilsin"
