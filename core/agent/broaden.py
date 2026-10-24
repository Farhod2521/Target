"""Handing the provider the audience as a starting point, not a boundary."""

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
    """The same spec with the provider allowed to look past it."""

    targeting: dict[str, Any]
    changed: tuple[str, ...] = ()


def broaden(targeting: Mapping[str, Any]) -> Broadening | None:
    """The spec with the provider's own audience expansion switched on."""
    if _is_on(targeting):
        return None

    spec = copy.deepcopy(dict(targeting))
    notes: list[Adjustment] = []
    fit(spec, notes, mode="automatic")
    return Broadening(
        targeting=spec, changed=tuple(dict.fromkeys(note.field for note in notes))
    )


def _is_on(targeting: Mapping[str, Any]) -> bool:
    """Whether the switch is already set, in whichever shape it arrives."""
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
