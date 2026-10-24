"""Taking a dead audience out of a spec the provider has stopped."""

import copy
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from typing import Any, Final

from core.targeting import EXCLUDE_KEY, INCLUDE_KEY

REPAIRABLE_KEY: Final = INCLUDE_KEY


@dataclass(frozen=True, slots=True)
class Repair:
    """A spec with the dead audiences gone, and what that cost."""

    targeting: dict[str, Any]
    dropped: tuple[str, ...]
    kept: int


def repair(targeting: Mapping[str, Any], *, unusable: Collection[str]) -> Repair | None:
    """The same spec without the audiences the provider will not deliver to."""
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
        spec.pop(REPAIRABLE_KEY, None)

    return Repair(targeting=spec, dropped=dropped, kept=len(kept))


def named_audiences(targeting: Mapping[str, Any]) -> tuple[str, ...]:
    """Every audience of the advertiser's own this spec names, either side."""
    return (*_ids(targeting.get(INCLUDE_KEY)), *_ids(targeting.get(EXCLUDE_KEY)))


def _ids(entries: Any) -> tuple[str, ...]:
    """The ids in one side of the spec, in whichever of the two shapes."""
    if not isinstance(entries, list | tuple):
        return ()
    return tuple(found for found in (_id(entry) for entry in entries) if found)


def _id(entry: Any) -> str:
    if isinstance(entry, Mapping):
        return str(entry.get("id") or "")
    return str(entry or "")


__all__ = ["REPAIRABLE_KEY", "Repair", "named_audiences", "repair"]
