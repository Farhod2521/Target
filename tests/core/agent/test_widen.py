"""core/agent/widen.py: one step outward, always the gentlest one left."""

from typing import Any

from core.agent import widen
from core.targeting import MAX_AGE, MAX_RADIUS_KM, MIN_AGE


def _pin(radius: int) -> dict[str, Any]:
    return {
        # Under ``geo_locations``, because that is where a real spec keeps
        # its pins - see ``core.targeting.pins``. A flat one reads the same
        # to the eye and leaves the radius step with nothing to widen.
        "geo_locations": {
            "custom_locations": [
                {
                    "latitude": "41.31",
                    "longitude": "69.24",
                    "radius": radius,
                    "distance_unit": "kilometer",
                }
            ]
        },
        "age_min": 25,
        "age_max": 45,
        "flexible_spec": [{"interests": [{"id": "1"}, {"id": "2"}]}],
    }


def test_the_radius_goes_first() -> None:
    """Reaching further costs the least meaning of the three.

    An owner who chose "within 5 km" was describing where their customers
    are, not asserting that nobody at 6 km would come. Their age range and
    their interests are narrower statements, so they are given up later.
    """
    found = widen(_pin(5))

    assert found is not None
    assert found.step == "radius"
    assert found.targeting["geo_locations"]["custom_locations"][0]["radius"] == 10
    assert found.detail == {"from_km": 5, "to_km": 10}


def test_the_radius_stops_at_the_ceiling() -> None:
    """Doubling past the provider's maximum is a request it refuses."""
    found = widen(_pin(50))

    assert found is not None
    pin = found.targeting["geo_locations"]["custom_locations"][0]
    assert pin["radius"] == MAX_RADIUS_KM


def test_a_maxed_radius_falls_through_to_the_age_range() -> None:
    """Already at the ceiling is not "cannot widen" - it is the next step."""
    found = widen(_pin(MAX_RADIUS_KM))

    assert found is not None
    assert found.step == "age"
    assert found.targeting["age_min"] == 20
    assert found.targeting["age_max"] == 50


def test_both_ends_of_the_age_range_move_together() -> None:
    """Moving one would turn a range somebody chose into a range nobody did.

    "25 to 45" becoming "25 to 50" reads as a decision about older
    customers. The agent made no such decision - it loosened a constraint.
    """
    found = widen({"age_min": 30, "age_max": 40})

    assert found is not None
    assert found.detail == {
        "from_min": 30,
        "from_max": 40,
        "to_min": 25,
        "to_max": 45,
    }


def test_the_age_range_stops_at_the_provider_bounds() -> None:
    found = widen({"age_min": 20, "age_max": 63})

    assert found is not None
    assert found.targeting["age_min"] == MIN_AGE
    assert found.targeting["age_max"] == MAX_AGE


def test_interests_go_last_and_go_whole() -> None:
    """No evidence exists for which interest is the dead weight.

    The provider reports spend per ad set and never per interest, so
    picking one to drop would be a guess dressed up as a decision.
    """
    found = widen({"age_min": MIN_AGE, "age_max": MAX_AGE, **_interests(6)})

    assert found is not None
    assert found.step == "interests"
    assert "flexible_spec" not in found.targeting
    assert found.detail == {"dropped": 6}


def test_the_widest_spec_has_nowhere_left_to_go() -> None:
    """``None`` is an answer. Proposing something anyway would be the agent
    inventing work to look busy."""
    assert widen({"age_min": MIN_AGE, "age_max": MAX_AGE}) is None
    assert widen({}) is None


def test_a_named_city_is_never_given_a_radius() -> None:
    """A delivery service covering Tashkent is not "within N km of" anything,
    and a circle drawn from the centre misses half its districts."""
    found = widen(
        {
            "geo_locations": {"cities": [{"key": "2420901"}]},
            "age_min": 25,
            "age_max": 45,
        }
    )

    assert found is not None
    assert found.step == "age"
    assert "custom_locations" not in found.targeting["geo_locations"]


def test_a_radius_in_another_unit_is_left_alone() -> None:
    """This product shows kilometres and sends kilometres. Doubling a number
    whose unit was not checked is how an ad set reaches the next country."""
    spec = _pin(5)
    spec["geo_locations"]["custom_locations"][0]["distance_unit"] = "mile"

    found = widen(spec)

    assert found is not None
    assert found.step == "age"


def test_the_original_spec_is_never_edited() -> None:
    """The stored audience is the undo. A widening that mutated it in place
    would leave nothing to restore."""
    spec = _pin(5)

    widen(spec)

    assert spec["geo_locations"]["custom_locations"][0]["radius"] == 5


def test_a_provider_string_radius_is_still_a_number() -> None:
    """Meta answers with strings as often as with numbers."""
    spec = _pin(5)
    spec["geo_locations"]["custom_locations"][0]["radius"] = "5"

    found = widen(spec)

    assert found is not None
    assert found.targeting["geo_locations"]["custom_locations"][0]["radius"] == 10


def test_a_pin_at_the_top_of_the_spec_is_not_a_pin() -> None:
    """The shape that hides this step, kept as a test.

    A spec with ``custom_locations`` at the top level is not one any
    provider accepts and not one anything in this codebase writes, so there
    is no radius here to widen - and the honest answer is to fall through
    to the ages rather than to edit a key that will never be sent.
    """
    found = widen(
        {
            "custom_locations": [{"radius": 5, "distance_unit": "kilometer"}],
            "age_min": 25,
            "age_max": 45,
        }
    )

    assert found is not None
    assert found.step == "age"


def _interests(count: int) -> dict[str, Any]:
    return {
        "flexible_spec": [{"interests": [{"id": str(index)} for index in range(count)]}]
    }
