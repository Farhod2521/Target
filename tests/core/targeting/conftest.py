"""Shared values for the targeting tests. No database, no network, no clock.

The catalogue is read once per session: it is a dozen files off disk and
nothing in these tests mutates it.
"""

import pytest
from adskit import MinorUnits

from core.targeting import (
    CATALOG_DIR,
    BusinessProfile,
    Interest,
    OnboardingAnswers,
    PresetCatalog,
)

PROVIDER = "meta"


@pytest.fixture(scope="session")
def catalog() -> PresetCatalog:
    return PresetCatalog.from_directory(CATALOG_DIR)


@pytest.fixture
def business() -> BusinessProfile:
    """A business complete enough for every preset in the catalogue.

    Both geo shapes are filled in: a pin for the categories that target a
    radius and a country for the two that deliver past the end of one.
    """
    return BusinessProfile(
        name="Test biznes",
        category="restaurant",
        lat="41.311081",
        lng="69.240562",
        city="Tashkent",
        country_code="UZ",
        locales=(67, 26),
        timezone="UTC",
        phone="+10000000000",
    )


@pytest.fixture
def answers() -> OnboardingAnswers:
    return OnboardingAnswers(
        category="restaurant",
        goal="calls",
        daily_budget_minor=MinorUnits(500),
        geo=("Tashkent",),
        radius_km=5,
        age_min=25,
        age_max=45,
        genders=(1, 2),
        interests=(
            Interest(label="Restoranlar", query="Restaurants", external_id="1"),
        ),
    )
