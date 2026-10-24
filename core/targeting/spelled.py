"""A targeting spec spelled out: which places, which interests, where shown."""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final, Literal

from core.targeting.describe import _DETAILED_KEYS, describe

_PLACE_KEYS: Final[tuple[str, ...]] = (
    "custom_locations",
    "places",
    "zips",
    "cities",
    "regions",
    "geo_markets",
    "countries",
    "country_groups",
)

_PLATFORMS_KEY: Final = "publisher_platforms"
_DEVICES_KEY: Final = "device_platforms"


@dataclass(frozen=True, slots=True)
class Place:
    """One place an audience is drawn from, and its radius when it has one."""

    name: str
    radius: int | None = None
    unit: str = ""


@dataclass(frozen=True, slots=True)
class AudienceWords:
    """What one spec is aimed at, by name."""

    places: tuple[Place, ...] = ()
    excluded_places: tuple[Place, ...] = ()
    age_min: int | None = None
    age_max: int | None = None
    genders: Literal["", "male", "female"] = ""
    detailed: tuple[tuple[str, ...], ...] = ()
    excluded_detailed: tuple[str, ...] = ()
    own_lists: tuple[str, ...] = ()
    excluded_lists: tuple[str, ...] = ()
    is_automatic: bool = False
    placements: tuple[tuple[str, tuple[str, ...]], ...] = ()
    devices: tuple[str, ...] = ()


def spell(spec: object) -> AudienceWords:
    """One spec, by name."""
    if not isinstance(spec, Mapping):
        return AudienceWords()
    sketch = describe(spec)
    exclusions = spec.get("exclusions")
    return AudienceWords(
        places=_places(spec.get("geo_locations")),
        excluded_places=_places(spec.get("excluded_geo_locations")),
        age_min=sketch.age_min,
        age_max=sketch.age_max,
        genders=sketch.genders,
        detailed=tuple(
            names
            for block in _entries(spec.get("flexible_spec"))
            if (names := _detailed_names(block))
        ),
        excluded_detailed=_detailed_names(exclusions),
        own_lists=tuple(_name(item) for item in _entries(spec.get("custom_audiences"))),
        excluded_lists=tuple(
            _name(item) for item in _entries(spec.get("excluded_custom_audiences"))
        ),
        is_automatic=sketch.is_automatic,
        placements=_placements(spec),
        devices=tuple(str(item) for item in _entries(spec.get(_DEVICES_KEY))),
    )


def _places(block: Any) -> tuple[Place, ...]:
    if not isinstance(block, Mapping):
        return ()
    return tuple(
        Place(
            name=_name(item),
            radius=_whole(item.get("radius")) if isinstance(item, Mapping) else None,
            unit=str(item.get("distance_unit", ""))
            if isinstance(item, Mapping)
            else "",
        )
        for key in _PLACE_KEYS
        for item in _entries(block.get(key))
        if _name(item)
    )


def _detailed_names(block: Any) -> tuple[str, ...]:
    if not isinstance(block, Mapping):
        return ()
    return tuple(
        name
        for key in _DETAILED_KEYS
        for item in _entries(block.get(key))
        if (name := _name(item))
    )


def _placements(spec: Mapping[str, Any]) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """``((platform, positions), ...)``. No positions is all of the platform's."""
    platforms = [str(item) for item in _entries(spec.get(_PLATFORMS_KEY))]
    return tuple(
        (
            platform,
            tuple(str(item) for item in _entries(spec.get(f"{platform}_positions"))),
        )
        for platform in platforms
    )


def _name(item: Any) -> str:
    """What a person would call an entry: its name, its address, its key."""
    if isinstance(item, str):
        return item
    if not isinstance(item, Mapping):
        return ""
    for key in ("name", "address_string", "key", "id"):
        value = item.get(key)
        if isinstance(value, str | int) and not isinstance(value, bool) and value != "":
            return str(value)
    latitude, longitude = item.get("latitude"), item.get("longitude")
    if isinstance(latitude, int | float) and isinstance(longitude, int | float):
        return f"a pin at {latitude:.4f}, {longitude:.4f}"
    return ""


def _entries(value: Any) -> Sequence[Any]:
    if isinstance(value, Sequence) and not isinstance(value, str | bytes):
        return value
    return ()


def _whole(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return None


__all__ = ["AudienceWords", "Place", "spell"]
