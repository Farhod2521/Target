"""core/agent/frequency: three levels (TZ 6.2), each said once, only upwards."""

from core.agent.frequency import Decision, Reading, decide, level_of, seen_too_often


def reading(frequency_hundredths: int, *, spend: int = 1_000) -> Reading:
    return Reading(
        adset_id="g",
        impressions=frequency_hundredths * 100,
        reach=10_000,
        spend_minor=spend,
    )


def test_the_bars_are_two_two_fifty_and_three() -> None:
    assert level_of(199) is None
    assert level_of(200) == "advice"
    assert level_of(253) == "warning"
    assert level_of(305) == "required"


def test_a_level_is_said_once() -> None:
    found = decide(
        reading=reading(204), said=["advice"], min_spend_minor=300, new_creative=False
    )

    assert found == Decision()


def test_levels_only_go_up() -> None:
    assert (
        decide(
            reading=reading(253),
            said=["advice"],
            min_spend_minor=300,
            new_creative=False,
        ).raise_to
        == "warning"
    )
    assert (
        decide(
            reading=reading(210),
            said=["warning"],
            min_spend_minor=300,
            new_creative=False,
        )
        == Decision()
    )


def test_falling_under_the_first_bar_starts_again() -> None:
    assert decide(
        reading=reading(199), said=["warning"], min_spend_minor=300, new_creative=False
    ).reset


def test_falling_under_three_takes_the_required_message_away() -> None:
    """TZ 6.2: the 3.00 message stays until a creative is added or the
    frequency falls under 3.00 - and 2.50 is not said a second time."""
    found = decide(
        reading=reading(270), said=["required"], min_spend_minor=300, new_creative=False
    )

    assert found == Decision(ease=True)


def test_a_new_creative_starts_again() -> None:
    assert decide(
        reading=reading(310), said=["required"], min_spend_minor=300, new_creative=True
    ).reset


def test_a_group_that_hardly_spent_is_not_read() -> None:
    assert (
        decide(
            reading=reading(310, spend=200),
            said=[],
            min_spend_minor=300,
            new_creative=False,
        )
        == Decision()
    )


def test_worn_out_starts_at_the_first_level() -> None:
    """The diagnosis and the audience rule call a group worn out at the
    frequency the morning's first level is sent at, and not below it."""
    assert seen_too_often(200)
    assert not seen_too_often(199)
    assert not seen_too_often(None)
