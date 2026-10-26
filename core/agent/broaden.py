"""Handing the provider the audience as a starting point, not a boundary.

The provider's own advice, carried out. Meta leaves recommendations on an
ad set - a code, a title and a paragraph - and the one this product can act
on says the same thing every time: let the platform deliver past the
audience you named.

**Not a step on the widening ladder.** :mod:`core.agent.widen` reaches
further out one layer at a time and each step gives up a piece of what the
advertiser asked for - a radius, an age range, the interests. This gives up
none of them: the interests stay in the spec, and what changes is their
*status*. In this mode they are where the provider starts looking rather
than the edge of who may be shown the advert - which is the difference the
review screen already has to explain, and the reason the two are separate
modules rather than a fourth step.

**The two corrections come with it, and they are not ours.** The provider
refuses this mode above an ``age_min`` of twenty-five and accepts no
``age_max`` at all, so switching it on means moving both. That arithmetic
is written once, in :func:`core.targeting.modes.fit`, and called from here
rather than copied - a second copy is a second thing to keep in step with a
limit the provider changes without telling anybody. What it reports is
carried out to the card, because an advertiser who typed an upper age is
about to be sent a spec without one and deserves the sentence.
"""

import copy
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from core.targeting import Adjustment
from core.targeting.modes import (
    AUTOMATION_FIELD,
    AUTOMATION_KEY,
    AUTOMATION_ON,
    fit,
)


@dataclass(frozen=True, slots=True)
class Broadening:
    """The same spec with the provider allowed to look past it.

    ``changed`` names the other fields that had to move to make the switch
    acceptable - ``age_min``, ``age_max`` - and it is empty in the ordinary
    case, where the ad set was already inside what the mode allows. It is
    on the card because it is the part the advertiser did not ask for.
    """

    targeting: dict[str, Any]
    changed: tuple[str, ...] = ()


def broaden(targeting: Mapping[str, Any]) -> Broadening | None:
    """The spec with the provider's own audience expansion switched on.

    ``None`` when it is already on, which is the ordinary answer for
    anything this product launches - and the reason this is checked here
    rather than trusted to the caller: the provider can leave a
    recommendation on an ad set whose switch is already set, and proposing
    a change that changes nothing is the one failure a button cannot
    recover from.

    The spec is copied, never edited in place: what arrives is the mirror's
    own JSON and the rest of the pass is still reading it.
    """
    if _is_on(targeting):
        return None

    spec = copy.deepcopy(dict(targeting))
    notes: list[Adjustment] = []
    fit(spec, notes, mode="automatic")
    return Broadening(
        targeting=spec, changed=tuple(dict.fromkeys(note.field for note in notes))
    )


def _is_on(targeting: Mapping[str, Any]) -> bool:
    """Whether the switch is already set, in whichever shape it arrives.

    The provider reads the value as an integer and answers with one, and a
    spec written elsewhere may carry a string or a boolean - an account
    inherited from a media buyer is exactly what this package exists to
    read. All three spellings of one are treated as one.
    """
    block = targeting.get(AUTOMATION_KEY)
    if not isinstance(block, Mapping):
        return False
    value = block.get(AUTOMATION_FIELD)
    if isinstance(value, bool):
        return value
    try:
        return int(value) == AUTOMATION_ON  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return False


__all__ = ["Broadening", "broaden"]
