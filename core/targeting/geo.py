"""Where the ads should be shown."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from adskit import GeoKind

from core.targeting.exceptions import InvalidTargeting

GeoMode = Literal["around", "places", "country"]

GeoOrigin = Literal["chosen", "derived"]

DISTANCE_UNIT = "kilometer"

NULL_ISLAND_DEGREES = 1.0

_ARRAYS: dict[GeoKind, str] = {
    "city": "cities",
    "region": "regions",
    "country": "countries",
}


@dataclass(frozen=True, slots=True)
class GeoPlace:
    """One city or region, as the provider named it."""

    key: str
    name: str = ""
    kind: GeoKind = "city"
    parent: str = ""

    @property
    def is_usable(self) -> bool:
        """A place with no key is a word. Words do not target."""
        return bool(self.key) and self.kind in _ARRAYS


@dataclass(frozen=True, slots=True)
class GeoChoice:
    """One campaign's geography, in the owner's terms."""

    mode: GeoMode = "country"
    places: tuple[GeoPlace, ...] = ()
    lat: str = ""
    lng: str = ""
    radius_km: int | None = None
    country_code: str = ""
    origin: GeoOrigin = "derived"

    @property
    def has_pin(self) -> bool:
        """Both coordinates, or neither, and somewhere a shop could be."""
        if not (self.lat and self.lng):
            return False
        try:
            lat, lng = float(self.lat), float(self.lng)
        except ValueError:
            return False
        return abs(lat) >= NULL_ISLAND_DEGREES or abs(lng) >= NULL_ISLAND_DEGREES

    @property
    def usable_places(self) -> tuple[GeoPlace, ...]:
        """The chosen places a provider would accept."""
        return tuple(place for place in self.places if place.is_usable)

    @property
    def is_usable(self) -> bool:
        """Whether this answer can be turned into a spec at all."""
        if self.mode == "around":
            return self.has_pin and bool(self.radius_km)
        if self.mode == "places":
            return bool(self.usable_places)
        return bool(self.country_code)

    @property
    def widened(self) -> bool:
        """Whether the owner is about to reach further than they asked."""
        return self.mode == "country" and self.origin == "derived"


def geo_locations(choice: GeoChoice) -> dict[str, Any]:
    """The provider's geography block for one answer."""
    if not choice.is_usable:
        raise InvalidTargeting(
            f"geography answer has nothing to target: mode={choice.mode}",
            field="geo_locations",
        )

    if choice.mode == "around":
        return {
            "custom_locations": [
                {
                    "latitude": choice.lat,
                    "longitude": choice.lng,
                    "radius": choice.radius_km,
                    "distance_unit": DISTANCE_UNIT,
                }
            ]
        }

    if choice.mode == "places":
        grouped: dict[str, list[dict[str, str]]] = {}
        for place in _without_overlap(choice.usable_places):
            grouped.setdefault(_ARRAYS[place.kind], []).append({"key": place.key})
        return dict(grouped)

    return {"countries": [choice.country_code]}


def _without_overlap(places: tuple[GeoPlace, ...]) -> list[GeoPlace]:
    """Each place once, and no city beside the region it lies in."""
    regions = {place.key for place in places if place.kind == "region"}
    seen: set[tuple[GeoKind, str]] = set()
    kept: list[GeoPlace] = []
    for place in places:
        if (place.kind, place.key) in seen:
            continue
        if place.kind == "city" and place.parent in regions:
            continue
        seen.add((place.kind, place.key))
        kept.append(place)
    return kept


def fallback(*, country_code: str) -> GeoChoice:
    """Everywhere, because nothing narrower was known."""
    return GeoChoice(mode="country", country_code=country_code, origin="derived")


def pins(spec: Mapping[str, Any]) -> list[dict[str, Any]]:
    """The custom locations one spec carries, from the only place they live."""
    block = spec.get("geo_locations")
    if not isinstance(block, Mapping):
        return []

    places = block.get("custom_locations")
    if not isinstance(places, list):
        return []

    return [place for place in places if isinstance(place, dict)]
