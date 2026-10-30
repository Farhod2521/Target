"""Whether two targeting specs aim at the same people.

Asked before an edit replaces an ad set's audience: the spec goes out whole,
so a copy that went stale - somebody changed the ad set in Ads Manager, or
Meta retired an interest - would quietly undo that change. The stored copy
and the ad set as Meta reads it now must therefore be compared, and a plain
``==`` cannot do it.

Meta rewrites what it keeps. A city sent as ``{"key": "2019233"}`` comes
back with a name, a region and a country; an ad set sent without an age
ceiling comes back with 65; a circle gains a primary city. So the two specs
are first reduced to what decides who sees the advert - places by key,
circles by centre and size, ages, genders, detailed targeting by id, owned
lists by id, the Advantage+ switch, the platforms - and compared there.

Placements below the platform (``instagram_positions`` and friends) are not
compared. Meta adds and renames positions as it ships surfaces, and a check
that refuses every edit after such a release protects nobody.
"""

from collections.abc import Mapping
from typing import Any, Final

_PLACE_KEYS: Final = (
    "cities",
    "regions",
    "zips",
    "places",
    "geo_markets",
    "electoral_districts",
    "neighborhoods",
    "subcities",
    "medium_geo_areas",
    "large_geo_areas",
    "metro_areas",
    "small_geo_areas",
)
_COORDINATE_PLACES: Final = 4

# The audience lists that are a set of ids, wherever Meta nests them.
_ID_LISTS: Final = ("custom_audiences", "excluded_custom_audiences", "locales")
_DETAILED: Final = (
    "interests",
    "behaviors",
    "life_events",
    "industries",
    "income",
    "family_statuses",
    "education_statuses",
    "work_positions",
    "work_employers",
    "education_schools",
    "education_majors",
    "relationship_statuses",
    "user_adclusters",
)

_AGE_MIN: Final = 18
_AGE_MAX: Final = 65
_EVERYBODY: Final = (1, 2)


def audience_of(spec: Mapping[str, Any]) -> dict[str, Any]:
    """The part of a spec that decides who sees the advert, in one spelling."""
    return {
        "geo": _geo(spec.get("geo_locations")),
        "excluded_geo": _geo(spec.get("excluded_geo_locations")),
        "age_min": _whole(spec.get("age_min"), _AGE_MIN),
        "age_max": _whole(spec.get("age_max"), _AGE_MAX),
        "genders": _genders(spec.get("genders")),
        "detailed": _blocks(spec.get("flexible_spec")),
        "excluded_detailed": _block(spec.get("exclusions")),
        **{key: _ids(spec.get(key)) for key in _ID_LISTS},
        "automatic": _automatic(spec.get("targeting_automation")),
        "platforms": sorted(
            str(item) for item in _list(spec.get("publisher_platforms"))
        ),
    }


def same_audience(first: Mapping[str, Any], second: Mapping[str, Any]) -> bool:
    """Whether the two specs aim at the same people, whoever spelled them."""
    return audience_of(first) == audience_of(second)


def _geo(block: Any) -> dict[str, Any]:
    if not isinstance(block, Mapping):
        return {}
    shape: dict[str, Any] = {}
    countries = sorted(str(item) for item in _list(block.get("countries")))
    if countries:
        shape["countries"] = countries
    for key in _PLACE_KEYS:
        keys = _ids(block.get(key), field="key")
        if keys:
            shape[key] = keys
    circles = sorted(_circle(item) for item in _list(block.get("custom_locations")))
    if circles:
        shape["circles"] = circles
    return shape


def _circle(item: Any) -> tuple[float, float, int, str]:
    if not isinstance(item, Mapping):
        return (0.0, 0.0, 0, "")
    return (
        round(_number(item.get("latitude")), _COORDINATE_PLACES),
        round(_number(item.get("longitude")), _COORDINATE_PLACES),
        _whole(item.get("radius"), 0),
        str(item.get("distance_unit") or "kilometer"),
    )


def _blocks(value: Any) -> list[dict[str, list[str]]]:
    """An OR of ANDs: each block's ids, the blocks in a stable order."""
    blocks = [_block(item) for item in _list(value)]
    return sorted((block for block in blocks if block), key=repr)


def _block(value: Any) -> dict[str, list[str]]:
    if not isinstance(value, Mapping):
        return {}
    return {key: ids for key in _DETAILED if (ids := _ids(value.get(key)))}


def _ids(value: Any, *, field: str = "id") -> list[str]:
    found = set()
    for item in _list(value):
        if isinstance(item, Mapping):
            if item.get(field) not in (None, ""):
                found.add(str(item[field]))
        elif item not in (None, ""):
            found.add(str(item))
    return sorted(found)


def _genders(value: Any) -> list[int]:
    wanted = sorted({_whole(item, 0) for item in _list(value)} - {0})
    return [] if not wanted or tuple(wanted) == _EVERYBODY else wanted


def _automatic(value: Any) -> int:
    return (
        _whole(value.get("advantage_audience"), 0) if isinstance(value, Mapping) else 0
    )


def _list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list | tuple) else []


def _whole(value: Any, default: int) -> int:
    try:
        return int(value) if value not in (None, "") else default
    except (TypeError, ValueError):
        return default


def _number(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


__all__ = ["audience_of", "same_audience"]
