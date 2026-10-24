"""Which questions of a survey are asked, given what has been picked so far."""

from collections.abc import Collection, Mapping, Sequence
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Rule:
    """One question's place, and what it hangs on (``parent`` 0 for nothing)."""

    position: int
    parent: int = 0
    options: tuple[int, ...] = ()


def asked_positions(
    rules: Sequence[Rule], picks: Mapping[int, Collection[int]]
) -> list[int]:
    """The positions asked, in order, for these picks by position."""
    asked: list[int] = []
    seen: set[int] = set()
    for rule in sorted(rules, key=lambda item: item.position):
        if rule.parent:
            if rule.parent not in seen:
                continue
            chosen = picks.get(rule.parent, ())
            if not any(option in chosen for option in rule.options):
                continue
        asked.append(rule.position)
        seen.add(rule.position)
    return asked


def rule_problem(
    *, position: int, parent: int, options: Collection[int], parent_options: int
) -> str:
    """Why a rule cannot stand, as a short code, or ``""`` when it can."""
    if not parent:
        return ""
    if parent >= position or parent < 1:
        return "later"
    if parent_options < 0:
        return "kind"
    if not options or any(not 0 <= option < parent_options for option in options):
        return "options"
    return ""
