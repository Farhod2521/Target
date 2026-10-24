"""The YAML catalogue: it loads, and every entry in it can actually build.

The important test in this file is the sweep at the bottom. A preset is
data, which means nobody type-checks it and nobody reviews it as code - the
only thing standing between a typo and a campaign that fails at creation is
a test that renders every combination the product offers.
"""

import dataclasses
from pathlib import Path

import pytest
from adskit import MinorUnits

from core.targeting import (
    BusinessProfile,
    CatalogError,
    OnboardingAnswers,
    PresetCatalog,
    PresetNotFound,
    build,
)

PROVIDER = "meta"

# The twelve the product offers. Written out rather than counted: this list
# changing is a product decision, and a test that counts files would let it
# happen by accident.
EXPECTED = (
    "auto",
    "beauty",
    "construction",
    "ecommerce",
    "education",
    "fitness",
    "medical",
    "real_estate",
    "restaurant",
    "retail_store",
    "services",
    "travel",
)


def _placeholders(node: object) -> list[str]:
    """Every string leaf that still carries a ``{``.

    Checking ``str(spec)`` would not work: a dict prints its own braces, and
    the test would pass or fail for reasons having nothing to do with the
    catalogue.
    """
    if isinstance(node, dict):
        return [found for value in node.values() for found in _placeholders(value)]
    if isinstance(node, list):
        return [found for value in node for found in _placeholders(value)]
    if isinstance(node, str) and "{" in node:
        return [node]
    return []


def _write(path: Path, body: str) -> Path:
    (path / "one.yaml").write_text(body, encoding="utf-8")
    return path


def test_every_category_the_product_offers_is_on_disk(catalog: PresetCatalog) -> None:
    keys = tuple(c.key for c in catalog.categories(provider=PROVIDER))

    assert keys == EXPECTED


def test_every_category_has_a_label_and_a_version(catalog: PresetCatalog) -> None:
    for category in catalog.categories(provider=PROVIDER):
        assert category.label
        assert category.version


def test_every_category_ships_interest_seeds(catalog: PresetCatalog) -> None:
    """The list the owner sees is never empty, with or without Claude.

    The seeds are the guarantee. An empty screen that says "the AI is
    unavailable" is the same as a broken product to the person looking at it.
    """
    for key in EXPECTED:
        seeds = catalog.seeds(provider=PROVIDER, category=key)

        assert len(seeds) >= 5, key


def test_no_seed_carries_a_provider_id(catalog: PresetCatalog) -> None:
    """Names are the source of truth; ids are a cache the provider fills.

    An id written into a data file is a promise the provider never made, and
    it fails at the latest possible moment - while the campaign is created.
    """
    for key in EXPECTED:
        for seed in catalog.seeds(provider=PROVIDER, category=key):
            assert seed.external_id == ""
            assert seed.label and seed.query


def test_a_seed_names_the_interest_in_both_languages(
    catalog: PresetCatalog,
) -> None:
    """Uzbek to read, English to search: the provider's catalogue is English."""
    seeds = catalog.seeds(provider=PROVIDER, category="restaurant")

    assert ("Restoranlar", "Restaurants") in tuple((s.label, s.query) for s in seeds)


def test_seeds_for_an_unknown_category_are_empty(catalog: PresetCatalog) -> None:
    assert catalog.seeds(provider=PROVIDER, category="submarines") == ()


def test_every_category_offers_at_least_one_goal(catalog: PresetCatalog) -> None:
    for key in EXPECTED:
        assert catalog.goals(provider=PROVIDER, category=key), key


def test_goals_keep_the_order_the_file_lists_them_in(
    catalog: PresetCatalog,
) -> None:
    """Which is the order the wizard shows, so the first one is a decision.

    ``goals`` is the lookup and returns everything, built or not: a launch
    answered months ago names a goal and the builder has to find it. What
    the wizard *offers* is narrower - see ``offered_goals``.
    """
    goals = tuple(
        p.goal for p in catalog.goals(provider=PROVIDER, category="restaurant")
    )

    assert goals[0] == "leads"
    assert "awareness" in goals


def test_an_unknown_combination_raises_rather_than_returning_none(
    catalog: PresetCatalog,
) -> None:
    with pytest.raises(PresetNotFound) as caught:
        catalog.find(provider=PROVIDER, category="restaurant", goal="sales")

    assert caught.value.category == "restaurant"
    assert caught.value.goal == "sales"


def test_an_unknown_provider_finds_nothing(catalog: PresetCatalog) -> None:
    """Not an empty catalogue - a different one. Google gets its own files."""
    assert catalog.categories(provider="google") == ()


@pytest.mark.parametrize("category", EXPECTED)
def test_every_preset_builds_and_leaves_no_placeholder(
    category: str,
    catalog: PresetCatalog,
    business: BusinessProfile,
) -> None:
    """The sweep. Every category, every goal, rendered and validated.

    A preset nobody has selected yet is a preset nobody has tested, and the
    first person to select it would be a customer.
    """
    profile = dataclasses.replace(business, category=category)

    for preset in catalog.goals(provider=PROVIDER, category=category):
        built = build(
            provider=PROVIDER,
            answers=OnboardingAnswers(
                category=category,
                goal=preset.goal,
                daily_budget_minor=MinorUnits(1000),
            ),
            business=profile,
            catalog=catalog,
            currency="USD",
        )

        assert built.objective.startswith("OUTCOME_"), preset.key
        assert built.optimization_goal, preset.key
        assert built.billing_event, preset.key
        assert _placeholders(built.targeting) == [], preset.key


@pytest.mark.parametrize("category", EXPECTED)
def test_every_preset_names_a_geography(category: str, catalog: PresetCatalog) -> None:
    """A spec without one is delivered worldwide, quietly and expensively."""
    for preset in catalog.goals(provider=PROVIDER, category=category):
        assert preset.targeting.get("geo_locations"), preset.key


def test_a_duplicated_goal_is_refused(tmp_path: Path) -> None:
    """Two entries for one combination means one of them silently never runs."""
    _write(
        tmp_path,
        """
provider: meta
category: cafe
label: "Kafe"
version: 1
targeting_base: {age_min: 20}
presets:
  - {goal: calls, label: "A", objective: O, optimization_goal: G, billing_event: B,
     sends_to: phone, call_to_action: CALL_NOW}
  - {goal: calls, label: "B", objective: O, optimization_goal: G, billing_event: B,
     sends_to: phone, call_to_action: CALL_NOW}
""",
    )

    with pytest.raises(CatalogError) as caught:
        PresetCatalog.from_directory(tmp_path)

    assert "cafe/calls" in str(caught.value)


def test_a_missing_field_names_the_file_it_is_missing_from(tmp_path: Path) -> None:
    _write(
        tmp_path,
        """
provider: meta
category: cafe
version: 1
presets:
  - {goal: calls, label: "A", objective: O, optimization_goal: G, billing_event: B}
""",
    )

    with pytest.raises(CatalogError) as caught:
        PresetCatalog.from_directory(tmp_path)

    assert "one.yaml" in str(caught.value)
    assert "label" in str(caught.value)


def test_a_preset_that_targets_nothing_is_refused(tmp_path: Path) -> None:
    _write(
        tmp_path,
        """
provider: meta
category: cafe
label: "Kafe"
version: 1
presets:
  - {goal: calls, label: "A", objective: O, optimization_goal: G, billing_event: B}
""",
    )

    with pytest.raises(CatalogError) as caught:
        PresetCatalog.from_directory(tmp_path)

    assert "targets nothing" in str(caught.value)


def test_a_schedule_block_is_refused(tmp_path: Path) -> None:
    """Barred from the catalogue.

    Nothing reads ``follow_business_hours`` - the launch always sends
    "start now", because a campaign is created paused and a person switches
    it on. Same rule as placements: a key that looks authoritative and
    decides nothing is refused.
    """
    _write(
        tmp_path,
        """
provider: meta
category: cafe
label: "Kafe"
version: 1
presets:
  - goal: calls
    label: "A"
    objective: O
    optimization_goal: G
    billing_event: B
    schedule:
      follow_business_hours: true
    targeting:
      age_min: 20
""",
    )

    with pytest.raises(CatalogError) as caught:
        PresetCatalog.from_directory(tmp_path)

    assert "schedule" in str(caught.value)


def test_a_preset_overrides_the_category_base_whole(tmp_path: Path) -> None:
    """Shallow merge: deep-merging two specs invents a third nobody wrote."""
    _write(
        tmp_path,
        """
provider: meta
category: cafe
label: "Kafe"
version: 2
targeting_base:
  geo_locations:
    countries: ["UZ"]
  age_min: 20
presets:
  - goal: calls
    label: "A"
    objective: O
    optimization_goal: G
    billing_event: B
    sends_to: phone
    call_to_action: CALL_NOW
    targeting:
      geo_locations:
        custom_locations: [{latitude: "1", longitude: "2"}]
""",
    )

    preset = PresetCatalog.from_directory(tmp_path).find(
        provider=PROVIDER, category="cafe", goal="calls"
    )

    assert preset.targeting["geo_locations"] == {
        "custom_locations": [{"latitude": "1", "longitude": "2"}]
    }
    assert preset.targeting["age_min"] == 20
    assert preset.version == "2"


def test_a_preset_may_not_say_where_the_ad_appears(tmp_path: Path) -> None:
    """Refused, not overwritten. A key that looks authoritative in a data
    file and decides nothing outlives the placement it names."""
    _write(
        tmp_path,
        """
provider: meta
category: cafe
label: "Kafe"
version: 2
targeting_base:
  age_min: 20
presets:
  - goal: calls
    label: "A"
    objective: O
    optimization_goal: G
    billing_event: B
    sends_to: phone
    call_to_action: CALL_NOW
    targeting:
      facebook_positions: [feed]
""",
    )

    with pytest.raises(CatalogError) as caught:
        PresetCatalog.from_directory(tmp_path)

    assert "facebook_positions" in str(caught.value)


def test_the_category_base_may_not_say_it_either(tmp_path: Path) -> None:
    _write(
        tmp_path,
        """
provider: meta
category: cafe
label: "Kafe"
version: 2
targeting_base:
  age_min: 20
  publisher_platforms: [facebook]
presets:
  - goal: calls
    label: "A"
    objective: O
    optimization_goal: G
    billing_event: B
    sends_to: phone
    call_to_action: CALL_NOW
""",
    )

    with pytest.raises(CatalogError) as caught:
        PresetCatalog.from_directory(tmp_path)

    assert "publisher_platforms" in str(caught.value)
