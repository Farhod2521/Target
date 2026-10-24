"""core/agent/frequency: three levels, each said once, only upwards."""

from core.agent.frequency import Decision, Reading, decide, level_of


def reading(frequency_hundredths: int, *, spend: int = 1_000) -> Reading:
    return Reading(
        adset_id="g",
        impressions=frequency_hundredths * 100,
        reach=10_000,
        spend_minor=spend,
    )


def test_the_bars_are_one_seventy_two_and_two_fifty() -> None:
    assert level_of(169) is None
    assert level_of(170) == "advice"
    assert level_of(205) == "warning"
    assert level_of(254) == "required"


def test_a_level_is_said_once() -> None:
    found = decide(
        reading=reading(172), said=["advice"], min_spend_minor=300, new_creative=False
    )

    assert found == Decision()


def test_levels_only_go_up() -> None:
    assert (
        decide(
            reading=reading(205),
            said=["advice"],
            min_spend_minor=300,
            new_creative=False,
        ).raise_to
        == "warning"
    )
    assert (
        decide(
            reading=reading(180),
            said=["warning"],
            min_spend_minor=300,
            new_creative=False,
        )
        == Decision()
    )


def test_falling_under_the_first_bar_starts_again() -> None:
    assert decide(
        reading=reading(160), said=["warning"], min_spend_minor=300, new_creative=False
    ).reset


def test_a_new_creative_starts_again() -> None:
    assert decide(
        reading=reading(260), said=["required"], min_spend_minor=300, new_creative=True
    ).reset


def test_a_group_that_hardly_spent_is_not_read() -> None:
    assert (
        decide(
            reading=reading(260, spend=200),
            said=[],
            min_spend_minor=300,
            new_creative=False,
        )
        == Decision()
    )
