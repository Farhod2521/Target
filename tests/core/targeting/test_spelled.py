"""A targeting spec by name: places, interests, lists and placements."""

from core.targeting.spelled import AudienceWords, Place, spell


def test_places_keep_their_names_and_radius() -> None:
    words = spell(
        {
            "geo_locations": {
                "cities": [
                    {
                        "key": "1",
                        "name": "Tashkent",
                        "radius": 10,
                        "distance_unit": "kilometer",
                    }
                ],
                "countries": ["UZ"],
                "custom_locations": [
                    {
                        "latitude": 41.3,
                        "longitude": 69.2,
                        "radius": 3,
                        "address_string": "Chilonzor 9",
                    }
                ],
            },
            "excluded_geo_locations": {"regions": [{"key": "2", "name": "Namangan"}]},
        }
    )

    assert words.places == (
        Place(name="Chilonzor 9", radius=3, unit=""),
        Place(name="Tashkent", radius=10, unit="kilometer"),
        Place(name="UZ"),
    )
    assert words.excluded_places == (Place(name="Namangan"),)


def test_interest_blocks_stay_apart_because_they_mean_and() -> None:
    words = spell(
        {
            "flexible_spec": [
                {
                    "interests": [
                        {"id": "1", "name": "Restaurants"},
                        {"id": "2", "name": "Fast food"},
                    ]
                },
                {"behaviors": [{"id": "3", "name": "Parents"}]},
            ],
            "exclusions": {"interests": [{"id": "4", "name": "Diet"}]},
        }
    )

    assert words.detailed == (("Restaurants", "Fast food"), ("Parents",))
    assert words.excluded_detailed == ("Diet",)


def test_ages_genders_lists_and_widening() -> None:
    words = spell(
        {
            "age_min": 25,
            "age_max": 45,
            "genders": [2],
            "custom_audiences": [{"id": "9", "name": "Mijozlar"}],
            "excluded_custom_audiences": [{"id": "8"}],
            "targeting_automation": {"advantage_audience": 1},
        }
    )

    assert (words.age_min, words.age_max, words.genders) == (25, 45, "female")
    assert words.own_lists == ("Mijozlar",)
    assert words.excluded_lists == ("8",)
    assert words.is_automatic is True


def test_placements_named_and_none_named_are_different_answers() -> None:
    named = spell(
        {
            "publisher_platforms": ["facebook", "instagram"],
            "instagram_positions": ["story", "reels"],
            "device_platforms": ["mobile"],
        }
    )

    assert named.placements == (("facebook", ()), ("instagram", ("story", "reels")))
    assert named.devices == ("mobile",)
    assert spell({"age_min": 18}).placements == ()


def test_a_malformed_spec_is_an_empty_audience_rather_than_an_error() -> None:
    assert spell("not a spec") == AudienceWords()
    assert spell({"geo_locations": "Tashkent", "flexible_spec": {"x": 1}}).places == ()
