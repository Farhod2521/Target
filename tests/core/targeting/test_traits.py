"""Behaviours and life events: the audience no interest could reach.

Nobody is "interested in" moving house or getting married. A removals firm,
a wedding hall and an estate agent have their entire audience in a list of
about a dozen rows that this package could not previously target, and this
file is about the two things that had to be true before it could.

The first is the split in the spec. The three catalogues go into three
different keys of one block, and a row in the wrong key is **not refused** -
the provider accepts it, matches it against nobody, and delivers an audience
narrower than anybody chose, with nothing in the answer to find it by.

The second is where they come from. No model writes these: they are closed
lists the provider publishes and matches by name exactly, so a name a model
invented resolves to nothing at all.
"""

import pytest
from adskit import MinorUnits

from core.targeting import (
    BusinessProfile,
    Interest,
    OnboardingAnswers,
    PresetCatalog,
    build,
    fallback,
)
from core.targeting.builder import DETAILED_KEYS
from core.targeting.exceptions import CatalogError
from core.targeting.loader import _traits

AGENT = BusinessProfile(
    name="Agentlik",
    category="real_estate",
    lat="41.311081",
    lng="69.240562",
    city="Tashkent",
    country_code="UZ",
)


def a_spec(catalog: PresetCatalog, *interests: Interest) -> dict:
    built = build(
        provider="meta",
        answers=OnboardingAnswers(
            category="real_estate",
            goal="leads",
            daily_budget_minor=MinorUnits(1000),
            radius_km=25,
            interests=interests,
            targeting_mode="interests",
        ),
        business=AGENT,
        catalog=catalog,
        currency="USD",
        geo=fallback(country_code="UZ"),
    )
    return dict(built.targeting).get("flexible_spec", [{}])[0]


def a_trait(kind: str, name: str = "Recently moved") -> Interest:
    return Interest(label=name, query=name, kind=kind, external_id="6001")  # type: ignore[arg-type]


# --- Which key each kind lands in ----------------------------------------
def test_a_life_event_is_not_written_into_the_interests_block(
    catalog: PresetCatalog,
) -> None:
    """The failure this whole field exists to prevent. The provider accepts
    the wrong key, matches it against nobody, and says nothing."""
    block = a_spec(catalog, a_trait("life_event"))

    assert "interests" not in block
    assert block["life_events"] == [{"id": "6001", "name": "Recently moved"}]


def test_a_behaviour_gets_the_providers_own_spelling(
    catalog: PresetCatalog,
) -> None:
    """``behaviors``, with the American spelling. Getting it wrong produces
    an empty result rather than an error."""
    block = a_spec(catalog, a_trait("behaviour", "Engaged Shoppers"))

    assert list(block) == ["behaviors"]


def test_all_three_share_one_block_rather_than_three(
    catalog: PresetCatalog,
) -> None:
    """Keys inside one block are OR-ed and separate blocks are AND-ed, so
    three blocks would target somebody who is interested in property *and*
    has recently moved *and* shops online - a fraction of a fraction, and
    nobody's intent here."""
    block = a_spec(
        catalog,
        Interest(label="Kvartira", query="Apartment", external_id="1"),
        a_trait("life_event"),
        a_trait("behaviour", "Engaged Shoppers"),
    )

    assert set(block) == {"interests", "life_events", "behaviors"}


def test_a_kind_that_was_never_confirmed_reaches_no_block(
    catalog: PresetCatalog,
) -> None:
    """An id is what makes a row targetable. Without one there is nothing to
    send, whichever catalogue it came from."""
    unconfirmed = Interest(label="Ko'chgan", query="Recently moved", kind="life_event")

    assert a_spec(catalog, unconfirmed) == {}


def test_a_kind_nobody_mapped_is_dropped_rather_than_guessed(
    catalog: PresetCatalog,
) -> None:
    """Reachable from a hand-edited draft. Silence widens the audience;
    guessing a key aims it at strangers."""
    block = a_spec(catalog, a_trait("industries"))

    assert block == {}


def test_every_kind_the_vocabulary_has_is_mapped() -> None:
    """The table is what stops a fourth kind being added and silently
    landing nowhere."""
    from typing import get_args

    from adskit import TraitKind

    assert set(get_args(TraitKind)) == set(DETAILED_KEYS)


# --- What the catalogue is allowed to declare ----------------------------
def test_a_seed_without_a_kind_is_refused() -> None:
    """The two classes are matched exactly, so a seed filed under the wrong
    one resolves to nothing - and "resolves to nothing" reads on every
    screen like a class this market does not offer."""
    with pytest.raises(CatalogError):
        _traits([{"label": "X", "query": "Recently moved"}], source="t.yaml")


def test_a_seed_claiming_to_be_an_interest_is_refused() -> None:
    """Interests are searched for and belong in ``interest_seeds``. A file
    that could put one here would be a file with two homes for one thing."""
    with pytest.raises(CatalogError):
        _traits(
            [{"label": "X", "query": "Coffee", "kind": "interest"}], source="t.yaml"
        )


def test_the_catalogue_declares_life_events_where_they_are_the_audience(
    catalog: PresetCatalog,
) -> None:
    """An estate agent's customer is somebody who has just moved or just
    married. There is no interest that finds them."""
    seeds = catalog.traits(provider="meta", category="real_estate")

    assert {seed.query for seed in seeds} >= {"Recently moved"}
    assert all(seed.kind == "life_event" for seed in seeds)


def test_most_categories_declare_none(catalog: PresetCatalog) -> None:
    """Not an omission. A clinic has no life event worth targeting, and a
    card headed "behaviours" with nothing in it reads as a product that
    forgot something."""
    assert catalog.traits(provider="meta", category="medical") == ()


def test_the_catch_all_category_declares_none(catalog: PresetCatalog) -> None:
    """Every business none of the other eleven fit lands here - pest control,
    marketing, a laundry - and no life event describes all their customers."""
    assert catalog.traits(provider="meta", category="services") == ()
