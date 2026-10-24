"""Taking a dead audience out of a spec the provider has stopped.

The one change in this package that is not about performance. Every other
rule reads figures and proposes a better bet; this one reads a fault and
proposes the only thing that can undo it. A provider that cannot deliver to
an audience an ad set names does not slow the ad set down - it stops it,
and every figure the rest of this package reasons about goes to nought.

**Only the inclusion side is ever touched, and that is a rule rather than a
simplification.** ``core.targeting.audiences`` states the asymmetry the
provider publishes: an exclusion is non-negotiable and an inclusion is a
boundary the platform may deliver past. Dropping an unusable *exclusion*
would show the advert to the very people somebody took the trouble to keep
away from it, which is worse than an advert that is switched off. So a
fault on that side is repaired by nobody here: the line stays on the
waiting list with the assistant a button away, and this returns ``None``.

**And it contradicts a sentence in that module on purpose.**
``AudienceChoice.unusable`` says nothing is dropped over an unusable
audience - a launch waits rather than going out wider than it was meant to.
That is right at launch, where the alternative is a campaign that starts a
day late. Here the alternative is an ad set that is already delivering
nothing, the change is a button rather than a silent edit, and how much
narrower the audience was is on the card: ``kept`` is what is left.

Meta-shaped, like :mod:`core.agent.widen` beside it and for the reason
CLAUDE.md gives - an intent abstraction invented from one provider would be
shaped like that provider. These two are the only modules in
``core.agent`` that know what a targeting key means.
"""

import copy
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from typing import Any, Final

from core.targeting import EXCLUDE_KEY, INCLUDE_KEY

# The one side a repair may edit. Named rather than used inline so the
# module docstring's rule is visible at the point it is enforced.
REPAIRABLE_KEY: Final = INCLUDE_KEY


@dataclass(frozen=True, slots=True)
class Repair:
    """A spec with the dead audiences gone, and what that cost.

    ``dropped`` is the provider's ids, not names: this package cannot read
    a table and the name is on the row the Django layer already holds.

    ``kept`` is how many of the advertiser's own audiences the ad set is
    still aimed at. It is the number the card has to print, because it is
    the difference between "one of your three lists is gone" and "the only
    list you named is gone, so this will now be shown to anybody the rest
    of the targeting allows". The same edit, two very different decisions.
    """

    targeting: dict[str, Any]
    dropped: tuple[str, ...]
    kept: int


def repair(targeting: Mapping[str, Any], *, unusable: Collection[str]) -> Repair | None:
    """The same spec without the audiences the provider will not deliver to.

    ``None`` when there is nothing to do, and it covers three different
    ordinary cases: the ad set names none of the unusable audiences, the
    fault is on the exclusion side where nothing here may edit, or the spec
    holds no audiences at all. All three end the same way - no proposal,
    and the fault stays on the waiting list where the provider's own words
    and the assistant can explain it.

    The spec is copied, never edited in place. What arrives is the mirror's
    own JSON, and a rule that mutated it would change what the *next* rule
    in the same pass is reasoning about.
    """
    dead = {str(item) for item in unusable if str(item)}
    if not dead:
        return None

    named = _ids(targeting.get(REPAIRABLE_KEY))
    dropped = tuple(item for item in named if item in dead)
    if not dropped:
        return None

    spec = copy.deepcopy(dict(targeting))
    kept = [entry for entry in spec.get(REPAIRABLE_KEY) or () if _id(entry) not in dead]
    if kept:
        spec[REPAIRABLE_KEY] = kept
    else:
        # An empty list is not the same as an absent key: the provider
        # reads one of them as an error and the other as "no such
        # constraint", which is what this ad set now has.
        spec.pop(REPAIRABLE_KEY, None)

    return Repair(targeting=spec, dropped=dropped, kept=len(kept))


def named_audiences(targeting: Mapping[str, Any]) -> tuple[str, ...]:
    """Every audience of the advertiser's own this spec names, either side.

    Read by the caller that has to decide which of an account's saved
    audiences are worth asking the provider about. Both sides, because the
    question is "is this list still usable" and the answer matters on the
    side this module refuses to edit too - it is what tells somebody their
    exclusion has stopped holding.
    """
    return (*_ids(targeting.get(INCLUDE_KEY)), *_ids(targeting.get(EXCLUDE_KEY)))


def _ids(entries: Any) -> tuple[str, ...]:
    """The ids in one side of the spec, in whichever of the two shapes.

    ``[{"id": ...}]`` is what this product writes and what the provider
    hands back; bare ids are accepted by the same field and appear in specs
    written elsewhere - an account inherited from a media buyer is exactly
    the case this package exists to read.
    """
    if not isinstance(entries, list | tuple):
        return ()
    return tuple(found for found in (_id(entry) for entry in entries) if found)


def _id(entry: Any) -> str:
    if isinstance(entry, Mapping):
        return str(entry.get("id") or "")
    return str(entry or "")


__all__ = ["REPAIRABLE_KEY", "Repair", "named_audiences", "repair"]
