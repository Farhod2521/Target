"""The goal whose ad opens the business's own Instagram profile.

Every provider word here is the one a live, paused ad set kept (probe,
2026-09-28) and the profile visit ads guide names: ``OUTCOME_TRAFFIC``,
``INSTAGRAM_PROFILE``, ``PROFILE_VISIT``, ``IMPRESSIONS`` and
``VIEW_INSTAGRAM_PROFILE``. The placement is Instagram only whatever the
owner answered - there is nowhere else the profile is.
"""

from pathlib import Path

import pytest

from core.targeting import (
    AccountFacts,
    BusinessProfile,
    CatalogError,
    Interest,
    OnboardingAnswers,
    PresetCatalog,
    build,
    closed_by,
    fallback,
    offer,
)
from core.targeting.placements import INSTAGRAM_PLACEMENTS, PLACEMENT_KEYS
from core.targeting.presets import CATALOG_DIR

PROVIDER = "meta"
CATALOG = PresetCatalog.from_directory(CATALOG_DIR)
CAFE = BusinessProfile(name="Osh Markazi", category="restaurant", country_code="UZ")
CONFIRMED = (Interest(label="Restoranlar", query="Restaurants", external_id="6003"),)


def every_profile_preset() -> list:  # type: ignore[type-arg]
    return [
        preset
        for category in CATALOG.categories(provider=PROVIDER)
        for preset in CATALOG.goals(provider=PROVIDER, category=category.key)
        if preset.goal == "profile_visits"
    ]


def built(goal: str, *, placement: str):  # type: ignore[no-untyped-def]
    return build(
        provider=PROVIDER,
        answers=OnboardingAnswers(
            category="restaurant",
            goal=goal,
            daily_budget_minor=1000,
            interests=CONFIRMED,
            placement_mode=placement,  # type: ignore[arg-type]
        ),
        business=CAFE,
        catalog=CATALOG,
        currency="USD",
        geo=fallback(country_code="UZ"),
        link="https://osh.uz",
    )


# --- The catalogue --------------------------------------------------------
def test_every_category_offering_a_site_visit_offers_the_profile_too() -> None:
    with_traffic = {
        category.key
        for category in CATALOG.categories(provider=PROVIDER)
        for preset in CATALOG.goals(provider=PROVIDER, category=category.key)
        if preset.goal == "traffic"
    }

    assert {preset.category for preset in every_profile_preset()} == with_traffic


def test_every_profile_preset_carries_the_words_meta_kept() -> None:
    for preset in every_profile_preset():
        assert preset.objective == "OUTCOME_TRAFFIC", preset.key
        assert preset.destination_type == "INSTAGRAM_PROFILE", preset.key
        assert preset.optimization_goal == "PROFILE_VISIT", preset.key
        assert preset.billing_event == "IMPRESSIONS", preset.key
        assert preset.call_to_action == "VIEW_INSTAGRAM_PROFILE", preset.key
        assert preset.opens_profile and not preset.needs_link, preset.key
        assert preset.is_deliverable and preset.offered, preset.key


def test_the_profile_may_carry_no_other_button(tmp_path: Path) -> None:
    """Another word opens the profile in a browser, behind a sign-in wall."""
    (tmp_path / "one.yaml").write_text(
        """
provider: meta
category: cafe
label: Kafe
version: "1"
targeting_base:
  geo_locations: {countries: [UZ]}
presets:
  - goal: profile_visits
    label: Profil
    objective: OUTCOME_TRAFFIC
    optimization_goal: PROFILE_VISIT
    billing_event: IMPRESSIONS
    sends_to: profile
    call_to_action: LEARN_MORE
    destination_type: INSTAGRAM_PROFILE
""",
        encoding="utf-8",
    )

    with pytest.raises(CatalogError, match="VIEW_INSTAGRAM_PROFILE"):
        PresetCatalog.from_directory(tmp_path)


# --- What is built --------------------------------------------------------
@pytest.mark.parametrize("placement", ["automatic", "standard"])
def test_the_advert_is_shown_on_instagram_only_whatever_was_answered(
    placement: str,
) -> None:
    spec = built("profile_visits", placement=placement)

    placed = {
        key: spec.targeting[key] for key in PLACEMENT_KEYS if key in spec.targeting
    }
    assert placed == {key: list(value) for key, value in INSTAGRAM_PLACEMENTS.items()}
    # The owner's answer is carried as it was: the destination overruled it.
    assert spec.placement_mode == placement


def test_explore_is_never_among_the_instagram_positions() -> None:
    assert not {"explore", "explore_home"} & set(
        INSTAGRAM_PLACEMENTS["instagram_positions"]
    )


def test_the_built_spec_names_the_profile() -> None:
    spec = built("profile_visits", placement="automatic")

    assert spec.objective == "OUTCOME_TRAFFIC"
    assert spec.destination_type == "INSTAGRAM_PROFILE"
    assert spec.optimization_goal == "PROFILE_VISIT"
    assert spec.call_to_action == "VIEW_INSTAGRAM_PROFILE"
    assert spec.opens_profile
    assert spec.campaign_type == "profile_visits"
    # No site is bought, so no site tags are sent either.
    assert spec.url_tags == ""


def test_a_site_visit_keeps_the_owner_s_placement() -> None:
    spec = built("traffic", placement="automatic")

    assert not any(key in spec.targeting for key in PLACEMENT_KEYS)


# --- Who may choose it ----------------------------------------------------
def test_the_row_is_closed_without_an_instagram_account() -> None:
    row = offer(provider=PROVIDER, key="profile_visits")
    assert row is not None

    assert closed_by(row, AccountFacts(has_pixel=True)) == ("instagram",)
    assert closed_by(row, AccountFacts(has_pixel=False, has_instagram=True)) == ()


def test_the_row_is_a_card_of_its_own_with_one_option() -> None:
    row = offer(provider=PROVIDER, key="profile_visits")
    assert row is not None

    assert row.outcome == "profile"
    assert row.is_choice
    assert row.kind.objective_group == "traffic"
    assert row.kind.provider_label == "Traffic"
    assert row.provider_destination_label == "Instagram profile"
