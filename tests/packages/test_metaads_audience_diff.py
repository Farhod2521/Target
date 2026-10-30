"""Whether two targeting specs aim at the same people.

The check stands between an edit and an ad set whose audience may have moved
since the edit was opened. Too strict, and every edit is refused because Meta
spelled the audience its own way; too loose, and an audience changed in Ads
Manager is written over. Both halves are pinned here.
"""

from typing import Any

from metaads.audience_diff import same_audience

SENT: dict[str, Any] = {
    "geo_locations": {"cities": [{"key": "2019233"}, {"key": "2019234"}]},
    "age_min": 25,
    "flexible_spec": [{"interests": [{"id": "6003"}, {"id": "6004"}]}],
    "custom_audiences": [{"id": "900"}],
}


# --- Meta's own spelling is not a change ---------------------------------
def test_meta_expanding_what_it_kept_is_the_same_audience() -> None:
    """Every ad set comes back with names, regions and defaults nobody sent."""
    held = {
        "geo_locations": {
            "cities": [
                {"key": "2019234", "name": "Samarqand", "region": "Samarqand"},
                {"key": "2019233", "name": "Tashkent", "country": "UZ"},
            ],
            "location_types": ["home", "recent"],
        },
        "age_min": 25,
        "age_max": 65,
        "flexible_spec": [
            {
                "interests": [
                    {"id": "6004", "name": "Tea"},
                    {"id": "6003", "name": "Coffee"},
                ]
            }
        ],
        "custom_audiences": [{"id": "900", "name": "Mijozlar"}],
        "targeting_automation": {"advantage_audience": 0},
        "instagram_positions": ["stream", "story"],
        "brand_safety_content_filter_levels": ["FACEBOOK_STANDARD"],
    }

    assert same_audience(SENT, held)


def test_both_genders_named_is_everybody() -> None:
    assert same_audience({**SENT, "genders": [1, 2]}, SENT)


def test_a_circle_is_the_same_whatever_meta_adds_to_it() -> None:
    sent = {
        "geo_locations": {
            "custom_locations": [
                {"latitude": 41.311081, "longitude": 69.240562, "radius": 5}
            ]
        }
    }
    held = {
        "geo_locations": {
            "custom_locations": [
                {
                    "latitude": "41.31108",
                    "longitude": "69.24056",
                    "radius": 5,
                    "distance_unit": "kilometer",
                    "primary_city_id": 2019233,
                }
            ]
        }
    }

    assert same_audience(sent, held)


# --- A real change is one ------------------------------------------------
def test_a_narrower_age_is_another_audience() -> None:
    assert not same_audience(SENT, {**SENT, "age_max": 40})


def test_one_interest_gone_is_another_audience() -> None:
    held = {**SENT, "flexible_spec": [{"interests": [{"id": "6003"}]}]}

    assert not same_audience(SENT, held)


def test_a_city_swapped_for_another_is_another_audience() -> None:
    held = {**SENT, "geo_locations": {"cities": [{"key": "2019233"}, {"key": "999"}]}}

    assert not same_audience(SENT, held)


def test_a_wider_circle_is_another_audience() -> None:
    first = {
        "geo_locations": {
            "custom_locations": [{"latitude": 41.3, "longitude": 69.2, "radius": 5}]
        }
    }
    second = {
        "geo_locations": {
            "custom_locations": [{"latitude": 41.3, "longitude": 69.2, "radius": 10}]
        }
    }

    assert not same_audience(first, second)


def test_advantage_audience_switched_on_is_another_audience() -> None:
    held = {**SENT, "targeting_automation": {"advantage_audience": 1}}

    assert not same_audience(SENT, held)


def test_one_gender_chosen_is_another_audience() -> None:
    assert not same_audience(SENT, {**SENT, "genders": [2]})


def test_an_owned_list_removed_is_another_audience() -> None:
    held = {key: value for key, value in SENT.items() if key != "custom_audiences"}

    assert not same_audience(SENT, held)
