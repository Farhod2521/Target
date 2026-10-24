"""Reading a finished spec back into something a person recognises.

The opposite direction to :mod:`core.targeting.builder`. The builder turns
answers into a
provider document; this turns a provider document back into the four facts
an owner asked about - where, how old, who, and roughly how many
interests - so a screen can say what a running ad set is actually aimed at
without asking the provider anything.

**Only what the document itself knows.** A spec names cities by the
provider's own key and never by name, so a sketch of a city audience can
honestly report *how many* places and not *which*. Resolving a key to
"Toshkent" is a network call, and no screen in this product may make one
inside the request that draws it - which is also why the dialog that edits
one ad set offers no way to change the place. Inventing a name here would
be worse than counting.

**A sketch is not an edit.** Nothing here is a step towards writing: what
this returns is lossy by design - it drops placements, locales, custom
audiences and everything else the spec carries - and a writer built from it
would delete every one of them. Editing goes the other way round, over a
copy of the stored document; see :mod:`core.targeting.revise`.

No clock, no database, no provider. A mapping in, a value out.
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final, Literal

# Where the audience is, in the only three shapes a spec can put it.
#
# ``around`` is a pin and a radius, ``places`` is a list of cities or
# regions, and ``country`` is one or more whole countries. The same three
# the wizard offers - see :mod:`core.targeting.geo` - because the same
# module writes them.
GeoShape = Literal["", "around", "places", "country"]

# The keys ``geo_locations`` groups named places under. Kept in step with
# ``geo._ARRAYS`` by the test beside this module: a fourth kind added
# there and not here would be counted as no places at all.
_PLACE_KEYS: Final[tuple[str, ...]] = (
    "cities",
    "regions",
    "zips",
    "places",
    # Neither of these is written by this product. They are Meta's, they
    # appear on campaigns mirrored out of Ads Manager, and a key nobody
    # counts is an audience aimed at four markets reported as aimed
    # nowhere - which looks like data rather than like an oversight.
    "geo_markets",
    "electoral_districts",
)
_COUNTRY_KEYS: Final[tuple[str, ...]] = ("countries", "country_groups")

# The blocks inside one flexible-spec entry that hold detailed targeting.
# Interests, behaviours and life events are three catalogues and one
# question - "how specific is this audience" - so the sketch counts them
# together rather than reporting three numbers nobody compares.
_DETAILED_KEYS: Final[tuple[str, ...]] = (
    "interests",
    "behaviors",
    "life_events",
    "industries",
    "income",
    "family_statuses",
    "education_statuses",
    "work_positions",
)

# Meta's numbers for the two answers it has. Absent or empty means
# everybody, which is the default and is reported as such.
_MALE: Final = 1
_FEMALE: Final = 2


@dataclass(frozen=True, slots=True)
class AudienceSketch:
    """What one spec is aimed at, as far as the spec itself can say.

    Every field has an "unknown" that is a real answer rather than a gap.
    ``geo`` is empty for a spec with no geography block at all, which is a
    spec targeting everywhere the account may reach - and a screen showing
    nothing there would be saying something much narrower.

    ``places`` is a count and never a list of names. See the module
    docstring: the document does not carry them.
    """

    geo: GeoShape = ""
    # For ``around``: how far, in the unit the spec was written in. The
    # wizard writes kilometres and the validator caps them, so this is
    # kilometres for everything this product builds - and a spec mirrored
    # from Ads Manager could be in miles, which is why the unit travels.
    radius: int | None = None
    radius_unit: str = ""
    # For ``places`` and ``country``: how many.
    places: int = 0
    age_min: int | None = None
    age_max: int | None = None
    # "" everybody · "male" · "female". Both numbers present is everybody
    # said the long way, and it is reported as everybody.
    genders: Literal["", "male", "female"] = ""
    # Interests, behaviours and life events together - see _DETAILED_KEYS.
    interests: int = 0
    # Whether the owner's own lists are part of this audience. A count is
    # not offered: what matters on a screen is that a saved list is
    # involved at all, and the names are in the account, not in the spec.
    uses_own_lists: bool = False
    excludes_own_lists: bool = False
    # Whether the provider was told to widen the audience on its own. The
    # one field here that changes what a reader should expect from the
    # other four: an automatic audience delivers past them.
    is_automatic: bool = False

    @property
    def is_empty(self) -> bool:
        """Whether the spec said nothing this sketch can report.

        True for ``{}`` and for a document whose every key is one this
        does not read. A screen showing an empty sketch should say the
        audience is not known rather than draw four blank fields.
        """
        return not (
            self.geo
            or self.age_min
            or self.age_max
            or self.genders
            or self.interests
            or self.uses_own_lists
        )


def describe(spec: object) -> AudienceSketch:
    """One spec, sketched.

    ``object`` and not ``Mapping`` on purpose, which is the type saying what
    the input actually is: a JSON column filled by a provider, or by
    somebody editing a row by hand. Annotating it as a mapping would be a
    promise made on this side of a boundary nothing checks, and the
    narrowing below would then read as dead code.

    Tolerant on the way in and exact on the way out. A string where an
    integer belongs is expected rather than exceptional - the field is
    dropped and the rest of the sketch survives, because a screen that
    raised on one malformed key would show nothing about an audience that
    is otherwise perfectly readable.
    """
    if not isinstance(spec, Mapping):
        return AudienceSketch()

    shape, radius, unit, places = _geography(spec.get("geo_locations"))
    return AudienceSketch(
        geo=shape,
        radius=radius,
        radius_unit=unit,
        places=places,
        age_min=_whole(spec.get("age_min")),
        age_max=_whole(spec.get("age_max")),
        genders=_genders(spec.get("genders")),
        interests=_detailed(spec.get("flexible_spec")),
        uses_own_lists=_nonempty(spec.get("custom_audiences")),
        excludes_own_lists=_nonempty(spec.get("excluded_custom_audiences")),
        is_automatic=_nonempty(spec.get("targeting_automation")),
    )


def _geography(block: Any) -> tuple[GeoShape, int | None, str, int]:
    """Which of the three shapes, and its one measurement.

    Checked in the order the shapes narrow. A spec carrying both a pin and
    a list of cities is not something this product writes, and if the
    provider hands one back the pin is the tighter statement of the two -
    so it is the one reported.
    """
    if not isinstance(block, Mapping):
        return "", None, "", 0

    pins = block.get("custom_locations")
    if isinstance(pins, Sequence) and not isinstance(pins, str | bytes) and pins:
        first = pins[0] if isinstance(pins[0], Mapping) else {}
        return (
            "around",
            _whole(first.get("radius")),
            str(first.get("distance_unit", "")),
            len(pins),
        )

    named = sum(_count(block.get(key)) for key in _PLACE_KEYS)
    if named:
        return "places", None, "", named

    countries = sum(_count(block.get(key)) for key in _COUNTRY_KEYS)
    if countries:
        return "country", None, "", countries

    return "", None, "", 0


def _detailed(flexible: Any) -> int:
    """How many detailed-targeting rows the audience names, across blocks.

    Summed over every block rather than read from the first. This product
    writes exactly one - see ``builder._detailed`` and why - but a campaign
    mirrored out of Ads Manager can carry several, and reporting the first
    block's count as the whole would understate an audience somebody built
    by hand.
    """
    if not isinstance(flexible, Sequence) or isinstance(flexible, str | bytes):
        return 0
    return sum(
        _count(block.get(key))
        for block in flexible
        if isinstance(block, Mapping)
        for key in _DETAILED_KEYS
    )


def _genders(value: Any) -> Literal["", "male", "female"]:
    """One answer, and everybody is the answer for three different inputs.

    Absent, empty, and both numbers present all mean the audience is not
    filtered by gender. Saying "erkaklar va ayollar" for the third would be
    a filter the owner did not set, printed as though they had.
    """
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        return ""
    numbers = {_whole(item) for item in value}
    if numbers == {_MALE}:
        return "male"
    if numbers == {_FEMALE}:
        return "female"
    return ""


def _count(value: Any) -> int:
    """Length, for something that is a list and zero for anything else."""
    if isinstance(value, Sequence) and not isinstance(value, str | bytes):
        return len(value)
    return 0


def _nonempty(value: Any) -> bool:
    """Whether a key carries anything at all.

    A mapping counts, which is what ``targeting_automation`` is, and so
    does a non-empty list, which is what the audience keys are.
    """
    if isinstance(value, Mapping):
        return bool(value)
    return _count(value) > 0


def _whole(value: Any) -> int | None:
    """An integer, or nothing.

    ``bool`` is refused explicitly: it is an ``int`` in Python and a
    ``True`` reaching an age field would render as the age 1.
    """
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return None
    return None


__all__ = ["AudienceSketch", "GeoShape", "describe"]
