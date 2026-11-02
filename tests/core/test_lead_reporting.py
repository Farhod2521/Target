from datetime import UTC, datetime, timedelta

from core.leads import CardFacts, card_signals, is_reportable

SUBMITTED = datetime(2026, 11, 1, 9, tzinfo=UTC)
LATER = SUBMITTED + timedelta(hours=2)


def _stages(**facts: object) -> list[str]:
    card = CardFacts(
        submitted_at=SUBMITTED,
        placed_at=SUBMITTED,
        **facts,  # type: ignore[arg-type]
    )
    return [signal.stage for signal in card_signals(card)]


def test_a_new_card_only_says_it_arrived() -> None:
    assert _stages(kind="new") == ["received"]


def test_a_quality_column_says_qualified() -> None:
    assert _stages(kind="open", qualified_at=LATER) == ["received", "qualified"]


def test_an_open_card_nobody_qualified_says_no_more() -> None:
    assert _stages(kind="open") == ["received"]


def test_a_sale_is_qualified_and_converted_even_unmarked() -> None:
    assert _stages(kind="won", closed_at=LATER, value_minor=5, currency="UZS") == [
        "received",
        "qualified",
        "converted",
    ]


def test_unqualified_says_nothing_of_quality() -> None:
    assert _stages(kind="junk", closed_at=LATER, qualified_at=LATER) == [
        "received",
        "unqualified",
    ]


def test_lost_keeps_only_that_it_arrived() -> None:
    assert _stages(kind="lost", closed_at=LATER, qualified_at=LATER) == ["received"]


def test_no_event_is_stamped_before_its_lead() -> None:
    card = CardFacts(
        kind="junk",
        submitted_at=LATER,
        placed_at=SUBMITTED,
        closed_at=SUBMITTED,
    )

    assert all(s.occurred_at > LATER for s in card_signals(card))


def test_the_window_keeps_a_margin() -> None:
    now = SUBMITTED + timedelta(days=7)

    assert not is_reportable(occurred_at=SUBMITTED, now=now, window_days=7)
    assert is_reportable(
        occurred_at=SUBMITTED + timedelta(hours=2), now=now, window_days=7
    )
