"""What the domain will and will not ask for when building on an audience.

Three fields and no number, which is the whole subject of this file. The
provider's percentage lives in the adapter; what is checked here is that a
width nobody was offered is refused, that a missing country stops the
operation rather than being guessed at, and that the seed carries which
provider issued it.

No Django, no network, no provider.
"""

import pytest
from adskit import ExternalRef

from core.audiences import BREADTHS, BreadthNotOffered, CountryUnknown, build_lookalike


def seed(provider: str = "meta") -> ExternalRef:
    return ExternalRef(provider=provider, level="audience", id="seed-1")


# --- What is offered -----------------------------------------------------
def test_three_widths_and_the_tightest_is_first() -> None:
    """The order is the picker's, and it starts where an advertiser with a
    good seed should: the tightest match."""
    assert BREADTHS == ("closest", "balanced", "broad")


def test_the_spec_carries_the_domains_word_and_no_number() -> None:
    """The absence is the design. Meta takes a percentage and Google takes
    an enum, and a domain holding the percentage would hold a figure the
    second platform cannot be told."""
    spec = build_lookalike(origin=seed(), breadth="closest", country="UZ")

    assert spec.breadth == "closest"
    assert not hasattr(spec, "ratio")


def test_the_seed_carries_which_provider_issued_it() -> None:
    """It matters more here than anywhere else in this project: one
    audience id looks exactly like another, so nothing but the ref could
    catch a seed belonging to a different platform."""
    spec = build_lookalike(
        origin=seed(provider="google"), breadth="broad", country="UZ"
    )

    assert spec.origin.provider == "google"
    assert spec.origin.level == "audience"


# --- What is refused -----------------------------------------------------
@pytest.mark.parametrize("breadth", ["", "0.05", "5", "similarity", "narrow"])
def test_a_width_nobody_was_offered_is_refused_by_name(breadth: str) -> None:
    """Reached by a hand-edited form rather than by a person choosing
    badly, so the value travels: it is the only thing worth knowing."""
    with pytest.raises(BreadthNotOffered) as caught:
        build_lookalike(origin=seed(), breadth=breadth, country="UZ")

    assert caught.value.breadth == breadth


@pytest.mark.parametrize("country", ["", " ", "U", "UZB", "Uzbekistan"])
def test_a_missing_or_malformed_country_stops_the_whole_operation(
    country: str,
) -> None:
    """Not a validation nicety. An audience of this kind is built inside
    one country's population, so without one there is nothing to take the
    top few per cent *of*.

    A country name is refused rather than truncated, exactly as the hashing
    rules refuse one: keeping the first two letters of "Uzbekistan" happens
    to be right and would be silently wrong for "United States".
    """
    with pytest.raises(CountryUnknown) as caught:
        build_lookalike(origin=seed(), breadth="balanced", country=country)

    assert caught.value.country == country


def test_the_country_is_folded_rather_than_demanded_in_upper_case() -> None:
    """The profile stores what somebody typed. Refusing a lower-case code
    would be refusing a correct answer for a reason nobody could see."""
    spec = build_lookalike(origin=seed(), breadth="balanced", country=" uz ")

    assert spec.country == "UZ"


def test_the_size_of_the_seed_is_deliberately_not_checked() -> None:
    """The provider asks for a hundred people **in the chosen country** and
    reports a total across everywhere. A check invented from the total
    would be arithmetic on a number that does not mean what it would have
    to mean, so that refusal is left to arrive in the provider's own words.

    Pinned as a test because the omission looks like a gap: this function
    takes no count and must keep taking none.
    """
    spec = build_lookalike(origin=seed(), breadth="closest", country="UZ")

    assert set(spec.model_dump()) == {"origin", "breadth", "country"}
