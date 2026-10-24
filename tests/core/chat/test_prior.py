"""The window against the one before it, worked out before the model reads it."""

from core.chat.prior import KindTotal, moves


def test_each_kind_moves_against_itself_and_its_price_too() -> None:
    found = moves(
        spend_now=12_000,
        spend_before=10_000,
        now=[KindTotal(kind="lead", count=300, spend_minor=12_000)],
        before=[KindTotal(kind="lead", count=400, spend_minor=10_000)],
    )

    assert found == (
        "spend up 20%",
        "leads down 25% (worse)",
        "cost of one of the leads up 60% (worse)",
    )


def test_a_cheaper_result_is_better_news() -> None:
    found = moves(
        spend_now=10_000,
        spend_before=10_000,
        now=[KindTotal(kind="chat", count=500, spend_minor=10_000)],
        before=[KindTotal(kind="chat", count=400, spend_minor=10_000)],
    )

    assert found == (
        "conversations up 25% (better)",
        "cost of one of the conversations down 20% (better)",
    )


def test_a_movement_too_few_results_carry_is_within_chance() -> None:
    """Two leads to one is half, and it is nothing."""
    found = moves(
        spend_now=10_000,
        spend_before=10_000,
        now=[KindTotal(kind="lead", count=1, spend_minor=10_000)],
        before=[KindTotal(kind="lead", count=2, spend_minor=10_000)],
    )

    assert "leads down 50% (within chance)" in found
    assert not any("worse" in line for line in found)


def test_two_kinds_are_never_compared_with_each_other() -> None:
    """Conversations this month against leads last month is no movement."""
    found = moves(
        spend_now=10_000,
        spend_before=10_000,
        now=[KindTotal(kind="chat", count=50, spend_minor=10_000)],
        before=[KindTotal(kind="lead", count=40, spend_minor=10_000)],
    )

    assert found == ("leads down 100% (worse)",)


def test_nothing_spent_before_is_nothing_to_compare_with() -> None:
    """A new account did not grow infinitely; it started."""
    found = moves(
        spend_now=10_000,
        spend_before=0,
        now=[KindTotal(kind="lead", count=40, spend_minor=10_000)],
        before=[],
    )

    assert found == ()


def test_a_collapse_onto_few_results_is_still_worse() -> None:
    """Forty leads to two is real, however few the two are."""
    found = moves(
        spend_now=10_000,
        spend_before=10_000,
        now=[KindTotal(kind="lead", count=2, spend_minor=10_000)],
        before=[KindTotal(kind="lead", count=40, spend_minor=10_000)],
    )

    assert "leads down 95% (worse)" in found
