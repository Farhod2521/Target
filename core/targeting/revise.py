"""Changing part of a running audience without losing the rest of it.

The direction :mod:`core.targeting.describe` refuses to go. That module
reads a finished spec into four facts a person recognises, and says in its
own docstring why it is not a step towards writing: what it returns is
lossy, and a writer built from it would delete placements, locales, saved
audiences and everything else it dropped.

**So editing works over a copy of the stored document.** The provider takes
a targeting spec whole - there is no call that widens a radius, only one
that replaces the audience - so an absent key is not "leave this alone", it
is "remove this". A dialog that edits four fields of a document with twenty
keys therefore has exactly one safe shape: copy all twenty, change the
four, send the result.

That is why every function here takes the whole spec and returns the whole
spec. Nothing is built from parts.

**A layer nobody named is not touched.** ``AudienceEdit`` is a set of
optional answers, and ``None`` means the question was not asked - the
dialog draws no radius field for an audience that is a list of cities, and
a ``None`` radius must not turn that list into a circle.

Meta-shaped, like :mod:`core.agent.widen` and :mod:`core.targeting.builder`
next door, and for the reason CLAUDE.md gives: an intent abstraction
invented from one provider would be shaped like that provider.

No clock, no database, no provider. A mapping in, a mapping out.
"""

import copy
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

from core.targeting.exceptions import InvalidTargeting
from core.targeting.geo import DISTANCE_UNIT, pins

# Meta's numbers for the two answers it has, the same pair
# :mod:`core.targeting.describe` reads back. Absent or empty means
# everybody, which is the default and is written as an absent key.
MALE: Final = 1
FEMALE: Final = 2

# The key detailed targeting lives under, and the reason it is removed
# whole rather than trimmed: the blocks inside it are an OR of ANDs, and
# taking one row out of one block changes what the other rows mean.
_DETAILED_KEY: Final = "flexible_spec"


@dataclass(frozen=True, slots=True)
class AudienceEdit:
    """The answers a person gave about one running audience.

    Every field is optional and ``None`` means **not asked**. That is not
    the same as "no constraint": clearing an age range is expressed by
    naming the widest one, and asking for everybody is ``genders=()``.
    The distinction is what lets one value carry an edit to a spec whose
    other layers this dialog never drew.

    ``keep_interests`` is a switch rather than a list because there is
    nothing here to choose from. Adding an interest means asking the
    provider what it is called and what its id is, which is a network call
    - see the audience section of the campaign dialog for why that call
    cannot happen inside the request that draws the form.
    """

    age_min: int | None = None
    age_max: int | None = None
    # ``()`` is everybody, said explicitly. ``None`` is "not asked".
    genders: tuple[int, ...] | None = None
    radius_km: int | None = None
    keep_interests: bool = True

    @property
    def is_empty(self) -> bool:
        """Whether this edit names nothing at all."""
        return (
            self.age_min is None
            and self.age_max is None
            and self.genders is None
            and self.radius_km is None
            and self.keep_interests
        )


def revise(spec: Mapping[str, Any], *, edit: AudienceEdit) -> dict[str, Any]:
    """The whole spec again, with only the named layers replaced.

    Deep-copied rather than shallow: the parts being changed are nested -
    a radius lives inside a list inside ``geo_locations`` - and a shallow
    copy would write through into the mirror row the caller read it from,
    which is the row the undo is photographed from.

    Raises rather than correcting. ``core.targeting.validators`` clamps a
    *built* spec because the numbers there came from a preset and an
    adjustment can be reported; these came from a person who typed them,
    and silently moving somebody's answer is a change they did not make and
    would not be told about.
    """
    if not isinstance(spec, Mapping) or not spec:
        # No document to copy is not an empty edit - it is an audience
        # nobody can put back afterwards, and the caller refuses it for
        # that reason too. Said here as well, because this is the function
        # that would otherwise invent a spec out of four fields.
        raise InvalidTargeting("there is no stored audience to change", field="spec")

    revised = copy.deepcopy(dict(spec))
    _ages(revised, edit=edit)
    _genders(revised, edit=edit)
    _radius(revised, edit=edit)
    _interests(revised, edit=edit)
    return revised


def changed(spec: Mapping[str, Any], *, edit: AudienceEdit) -> bool:
    """Whether this edit would actually move anything.

    Asked before a write, because a spec replaced with itself is an audit
    row claiming a change nobody made - and, at the provider, a fresh
    learning phase paid for with somebody's budget in exchange for
    nothing.
    """
    return revise(spec, edit=edit) != dict(spec)


def _ages(spec: dict[str, Any], *, edit: AudienceEdit) -> None:
    """The age range, both ends together or neither.

    One end on its own is refused rather than half-applied. "25 to 45"
    becoming "25 to none" is not a narrower question than the one that was
    asked, it is a different one - and the provider reads a missing
    ``age_max`` as sixty-five.
    """
    if edit.age_min is None and edit.age_max is None:
        return
    if edit.age_min is None or edit.age_max is None:
        raise InvalidTargeting("an age range needs both ends", field="age")
    if edit.age_min > edit.age_max:
        raise InvalidTargeting(
            f"age_min {edit.age_min} is above age_max {edit.age_max}", field="age"
        )

    spec["age_min"] = edit.age_min
    spec["age_max"] = edit.age_max


def _genders(spec: dict[str, Any], *, edit: AudienceEdit) -> None:
    """Who to show it to, where an empty answer removes the key entirely.

    An absent ``genders`` and an empty list mean the same thing to the
    provider - everybody - and sending the empty list is an error on some
    fields and a no-op on others. The same rule ``validators._drop_empty``
    follows, for the same reason.
    """
    if edit.genders is None:
        return

    wanted = tuple(value for value in edit.genders if value in (MALE, FEMALE))
    if len(wanted) != len(set(wanted)):
        raise InvalidTargeting("a gender was named twice", field="genders")

    if not wanted or set(wanted) == {MALE, FEMALE}:
        spec.pop("genders", None)
        return
    spec["genders"] = list(wanted)


def _radius(spec: dict[str, Any], *, edit: AudienceEdit) -> None:
    """How far the circle reaches, for an audience that is a circle.

    Only pins have one. A list of cities and a whole country have no
    radius - a delivery service covering Tashkent is not "within N km of"
    anything - and writing one for them would replace the outline of a
    city with a circle that misses half its districts.

    Locations written in another unit are left alone, which is
    :mod:`core.agent.widen`'s rule and right for the same reason: this
    product shows kilometres and sends kilometres, and rewriting a number
    whose unit we did not check is how an ad set ends up advertising to a
    neighbouring country.
    """
    if edit.radius_km is None:
        return
    if edit.radius_km <= 0:
        raise InvalidTargeting(
            f"radius {edit.radius_km} is not a distance", field="radius"
        )

    for place in pins(spec):
        if place.get("distance_unit", DISTANCE_UNIT) != DISTANCE_UNIT:
            continue
        place["radius"] = edit.radius_km


def _interests(spec: dict[str, Any], *, edit: AudienceEdit) -> None:
    """Stop narrowing by interest at all, when that is what was asked.

    Removed whole rather than trimmed - see ``_DETAILED_KEY``. The reverse
    is not offered here: putting interests back means naming them, and a
    name is worth nothing to the provider without the id it issued.

    Not a one-way door, though it is written like one. The spec being
    replaced is photographed into ``ActionLog.previous_state`` before the
    write, and the campaign's own history offers it back - see
    ``apps.ads.services.revert_change``.
    """
    if edit.keep_interests:
        return
    spec.pop(_DETAILED_KEY, None)


__all__ = ["FEMALE", "MALE", "AudienceEdit", "changed", "revise"]
