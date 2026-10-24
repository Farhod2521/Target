"""Where the ads should be shown.

The other half of a targeting spec. Taken from the business profile - a
pin if the owner has one, the whole country if not - a campaign's reach
would be a property of a *profile row* rather than of the campaign, with
two consequences: a business with two branches could describe only one of
them, and editing the profile for a new campaign would silently retarget
every older one that was ever rebuilt.

So geography is an answer, like the budget and the age range: it belongs to
one campaign, it is frozen with it, and changing it later changes only the
campaign it was changed on.

Three shapes, because that is how many honest answers there are:

``around``   a pin and a radius - "within 5 km of the shop". What ten of
             the twelve presets assume, and the only one that needs
             coordinates.
``places``   named cities or regions - "Tashkent", or "Tashkent and
             Samarkand". A delivery service covering a whole city has no
             radius: a radius drawn from the centre would cut off half the
             districts it delivers to, which is worse than no radius at all.
``country``  everything. Right for an online shop, and the fallback when
             nothing else is known.

No clock, no database, no provider call. Keys arrive already resolved -
turning "Toshkent" into a key is the adapter's job, and the reason it is
not done here is that keys expire and catalogues are data.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from adskit import GeoKind

from core.targeting.exceptions import InvalidTargeting

# What a geography answer is aimed at.
GeoMode = Literal["around", "places", "country"]

# Whether a person decided this or we assembled it from what we had.
#
# The distinction the review screen turns into a sentence. "Butun
# mamlakat" chosen by an owner is a decision and needs no comment; the same
# spec arrived at because nobody said anything is a campaign about to spend
# a city's budget on a country, and saying so is the difference between a
# product that widened an audience and one that did it quietly.
GeoOrigin = Literal["chosen", "derived"]

# The unit every radius in this package is expressed in. Providers accept
# miles too; nothing here offers them, because a product that shows one unit
# and sends another is one rounding error away from a support ticket.
DISTANCE_UNIT = "kilometer"

# How close to 0,0 a pin may sit before it stops counting as one. The square
# is open sea on every side, so nothing in it is a place a business could be.
NULL_ISLAND_DEGREES = 1.0

# Which provider list a place goes into. Cities and regions are separate
# arrays in a spec, and a city sent among the regions is accepted, ignored,
# and delivers to the wrong outline.
_ARRAYS: dict[GeoKind, str] = {
    "city": "cities",
    "region": "regions",
    "country": "countries",
}


@dataclass(frozen=True, slots=True)
class GeoPlace:
    """One city or region, as the provider named it.

    ``key`` is the provider's, and it is the only part that targets
    anything. ``name`` is carried beside it so a screen can show what was
    chosen without another round trip, and so an audit row months later
    says "Tashkent" rather than "2420901".
    """

    key: str
    name: str = ""
    kind: GeoKind = "city"
    # The provider's key for the region a city lies in, when the lookup
    # said. Empty for a region, and for a city found before it was kept.
    parent: str = ""

    @property
    def is_usable(self) -> bool:
        """A place with no key is a word. Words do not target."""
        return bool(self.key) and self.kind in _ARRAYS


@dataclass(frozen=True, slots=True)
class GeoChoice:
    """One campaign's geography, in the owner's terms.

    Frozen, and stored on the launch rather than derived at send time. That
    is the whole point: a campaign that was aimed at Tashkent in January is
    still aimed at Tashkent in March, whatever the profile says by then.
    """

    mode: GeoMode = "country"
    places: tuple[GeoPlace, ...] = ()
    # Strings, like ``BusinessProfile.lat``: these end up in a JSON column
    # and in a request body, and Decimal survives neither without a custom
    # encoder.
    lat: str = ""
    lng: str = ""
    radius_km: int | None = None
    # ISO-3166 alpha-2. Needed even in the other two modes, because it is
    # what the fallback falls back *to*.
    country_code: str = ""
    origin: GeoOrigin = "derived"

    @property
    def has_pin(self) -> bool:
        """Both coordinates, or neither, and somewhere a shop could be.

        One of them is not half an answer. A latitude with no longitude is
        a point on the prime meridian, and a radius drawn around it
        delivers to the Atlantic.

        A pin within a degree of 0,0 is no pin either. That square is open
        sea, and a point there is a map's untouched centre or an empty
        field read as zero - never a place somebody advertises from.
        """
        if not (self.lat and self.lng):
            return False
        try:
            lat, lng = float(self.lat), float(self.lng)
        except ValueError:
            return False
        return abs(lat) >= NULL_ISLAND_DEGREES or abs(lng) >= NULL_ISLAND_DEGREES

    @property
    def usable_places(self) -> tuple[GeoPlace, ...]:
        """The chosen places a provider would accept.

        Unresolved ones are kept on the launch rather than dropped - the
        screen has to be able to say which name it could not find - so they
        are filtered here instead, at the one point where the answer stops
        being something to look at and starts being something to send.
        """
        return tuple(place for place in self.places if place.is_usable)

    @property
    def is_usable(self) -> bool:
        """Whether this answer can be turned into a spec at all.

        Not a validity check on the owner's input - the form does that. It
        is the question asked one layer later, after a lookup may have come
        back empty: a chosen city that the provider did not recognise
        leaves a ``places`` answer with nothing in it, and a campaign built
        from it would target the entire world.
        """
        if self.mode == "around":
            return self.has_pin and bool(self.radius_km)
        if self.mode == "places":
            return bool(self.usable_places)
        return bool(self.country_code)

    @property
    def widened(self) -> bool:
        """Whether the owner is about to reach further than they asked.

        True only for a country nobody chose. An owner who picked "the
        whole country" gets no warning about it, because there is nothing
        to warn them about.
        """
        return self.mode == "country" and self.origin == "derived"


def geo_locations(choice: GeoChoice) -> dict[str, Any]:
    """The provider's geography block for one answer.

    Provider-shaped on the way out, exactly like the spec it goes into: the
    vocabulary flips at this boundary and CLAUDE.md says why - an intent
    abstraction invented from one provider would be shaped like that
    provider anyway.

    Raises rather than returning something smaller. A geography block that
    could not be built is not a wider campaign, it is a campaign delivering
    somewhere nobody chose, and the caller has a fallback to reach for.
    """
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
    """Each place once, and no city beside the region it lies in.

    The provider refuses both pairs outright - "some locations conflict
    with each other" - rather than tidying them. Dropping the city loses
    nobody: the region it lies in is still there and covers it.
    """
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
    """Everywhere, because nothing narrower was known.

    A named constructor rather than a bare ``GeoChoice(...)`` at four call
    sites, so that the one property that matters here - that nobody chose
    this - cannot be forgotten at the fourth.
    """
    return GeoChoice(mode="country", country_code=country_code, origin="derived")


def pins(spec: Mapping[str, Any]) -> list[dict[str, Any]]:
    """The custom locations one spec carries, from the only place they live.

    Under ``geo_locations``, which is where :func:`geo_locations` writes
    them and where :mod:`core.targeting.describe` reads them from. A
    top-level ``custom_locations`` is not a spec any provider accepts, so a
    reader looking there finds nothing - and finds it silently, since an
    absent pin and a pin in the wrong place are the same empty list.

    Handed back as they are rather than copied. A caller that means to edit
    a spec copies it first; both callers here do, and the copy is the thing
    that gets written.
    """
    block = spec.get("geo_locations")
    if not isinstance(block, Mapping):
        return []

    places = block.get("custom_locations")
    if not isinstance(places, list):
        return []

    return [place for place in places if isinstance(place, dict)]
