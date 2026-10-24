"""The bar a weekly movement has to clear before anybody explains it."""

from core.metrics import MIN_WEEK_LEADS, is_beyond_noise, noise_pct


def test_a_week_with_no_events_has_no_bar_at_all() -> None:
    """``None``, and deliberately not a number.

    Zero would mean every movement clears it and a hundred would mean a
    specific bar was measured. Neither happened: there is no rate to
    compare, which is a different answer from "the movement was small".
    """
    assert noise_pct(now=0, before=10) is None
    assert noise_pct(now=10, before=0) is None


def test_the_bar_is_the_two_counting_errors_added() -> None:
    """One over the square root of each, as a percentage.

    Ten leads against ten gives about sixty-three percent, which is the
    honest reading of a week that small - and the reason the report is
    usually silent on a small account.
    """
    assert noise_pct(now=10, before=10) == 63
    assert noise_pct(now=100, before=100) == 20


def test_the_bar_falls_as_the_counts_grow() -> None:
    """More evidence, smaller movements worth talking about."""
    assert noise_pct(now=400, before=400) < noise_pct(now=25, before=25)


def test_a_tiny_week_is_rejected_however_large_the_movement() -> None:
    """The floor is a separate test from the error bar, and this is why.

    Two leads becoming four is a hundred percent by arithmetic and nothing
    at all by evidence.
    """
    assert not is_beyond_noise(percent=100, now=4, before=2)


def test_one_large_side_does_not_rescue_a_tiny_one() -> None:
    """Four against forty fails on the four.

    A single combined test would let the forty carry it, which is how a
    comparison ends up resting on a count that cannot hold it.
    """
    assert not is_beyond_noise(percent=90, now=4, before=40)


def test_a_movement_smaller_than_its_own_error_is_rejected() -> None:
    assert not is_beyond_noise(percent=30, now=10, before=10)


def test_a_movement_larger_than_its_own_error_passes() -> None:
    assert is_beyond_noise(percent=70, now=10, before=10)


def test_the_floor_is_the_one_the_rest_of_the_report_uses() -> None:
    """A constant rather than a literal in three places."""
    assert MIN_WEEK_LEADS == 5
    assert not is_beyond_noise(percent=999, now=MIN_WEEK_LEADS - 1, before=50)
