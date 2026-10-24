"""How many adverts one daily budget gives a fair share to.

Arithmetic only. The warning built on it lives in ``apps.ads``; what is
pinned here is the number, and the two edges where it has to stay quiet.
"""

from core.targeting.budget import (
    PER_AD_FLOOR_MULTIPLE,
    ads_budget_carries,
    per_ad_floor,
)


def test_five_dollars_on_a_one_dollar_floor_carries_two_adverts() -> None:
    """The launch this exists for: USD 5.00 a day across five adverts on a
    goal whose floor is USD 1.00. Meta spent it on one or two of them."""
    assert ads_budget_carries(daily_budget_minor=500, floor_minor=100, ads=5) == 2


def test_each_advert_needs_the_multiple_of_the_floor() -> None:
    floor = 100
    three = floor * PER_AD_FLOOR_MULTIPLE * 3

    assert ads_budget_carries(daily_budget_minor=three, floor_minor=floor, ads=5) == 3
    assert (
        ads_budget_carries(daily_budget_minor=three - 1, floor_minor=floor, ads=5) == 2
    )


def test_a_budget_at_the_floor_still_carries_one() -> None:
    """One advert takes the whole budget and has nothing to be compared
    against, so there is no smaller answer to give."""
    assert ads_budget_carries(daily_budget_minor=100, floor_minor=100, ads=5) == 1


def test_an_unknown_floor_flags_nothing() -> None:
    """Zero is "the provider has not said", as it is for ``daily_floor``."""
    assert ads_budget_carries(daily_budget_minor=100, floor_minor=0, ads=5) == 5


def test_the_sum_the_warning_names_is_the_share_the_count_uses() -> None:
    """USD 1.00 floor: each advert should have USD 2.00, so USD 5.00 over
    three is under it and over two is not."""
    assert per_ad_floor(floor_minor=100) == 200
    assert per_ad_floor(floor_minor=0) == 0
    assert ads_budget_carries(daily_budget_minor=500, floor_minor=100, ads=3) < 3
