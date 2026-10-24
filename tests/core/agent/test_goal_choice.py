"""A reading of the owner's words as one row of the first step's table."""

from core.agent import GoalChoice, read_goal_choice
from core.agent.goal_table import render_rows
from core.targeting import OFFERS

ROWS = [row.key for row in OFFERS]
TEXT = "Jiddiy mijozlar menga qo'ng'iroq qilsin"


def intent(
    choice: str, *alternatives: str, quote: str = "", sale: bool = False
) -> GoalChoice:
    return GoalChoice(
        choice=choice, alternatives=list(alternatives), quote=quote, wants_sale=sale
    )


def test_a_row_in_the_table_is_found_with_its_alternatives() -> None:
    reading = read_goal_choice(
        intent("calls_ready", "chat_conversations", quote="Jiddiy mijozlar"),
        rows=ROWS,
        text=TEXT,
    )

    assert (reading.state, reading.row, reading.alternatives) == (
        "found",
        "calls_ready",
        ("chat_conversations",),
    )
    assert reading.quote == "Jiddiy mijozlar"


def test_keys_outside_the_table_are_dropped() -> None:
    reading = read_goal_choice(
        intent("calls_ready", "OUTCOME_LEADS", "made_up"), rows=ROWS, text=TEXT
    )

    assert reading.alternatives == ()


def test_a_dropped_choice_is_replaced_by_a_named_alternative() -> None:
    reading = read_goal_choice(intent("made_up", "calls_many"), rows=ROWS, text=TEXT)

    assert (reading.state, reading.row) == ("found", "calls_many")


def test_no_choice_is_unclear_even_with_alternatives() -> None:
    """Alternatives beside nothing are not promoted into a guess."""
    reading = read_goal_choice(intent("", "calls_many"), rows=ROWS, text=TEXT)

    assert reading.state == "unclear"


def test_the_choice_is_never_its_own_alternative() -> None:
    reading = read_goal_choice(
        intent("calls_many", "calls_many", "seen_widely"),
        rows=ROWS,
        text=TEXT,
    )

    assert reading.alternatives == ("seen_widely",)


def test_a_sale_with_no_choice_is_offered_a_visit() -> None:
    reading = read_goal_choice(intent("", sale=True), rows=ROWS, text="onlayn sotuv")

    assert (reading.state, reading.row) == ("sale", "site_page_views")


def test_a_quote_the_owner_did_not_write_is_dropped() -> None:
    reading = read_goal_choice(
        intent("calls_ready", quote="serious buyers"), rows=ROWS, text=TEXT
    )

    assert reading.quote == ""


def test_a_closed_row_is_still_a_valid_answer() -> None:
    """The screen shows it with its reason; the reading does not hide it."""
    reading = read_goal_choice(intent("site_requests"), rows=ROWS, text="saytda ariza")

    assert reading.row == "site_requests"


def test_the_model_is_shown_every_row_its_defaults_and_what_is_closed() -> None:
    text = render_rows(
        offers=OFFERS,
        defaults=frozenset({"form_leads"}),
        closed={"site_requests": "Piksel ulanmagan"},
    )

    for row in OFFERS:
        assert f"`{row.key}`" in text
    assert (
        "`form_leads` (Leads · Instant forms · Maximize number of leads; default)"
        in text
    )
    assert "to'sqin: Piksel ulanmagan" in text
