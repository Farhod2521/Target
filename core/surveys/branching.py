"""Which questions of a survey are asked, given what has been picked so far.

A question either is always asked, or hangs on an earlier choice question:
it is asked when one of its listed options was picked there, and only when
that earlier question was itself asked. A chain therefore closes as a
whole - "No" on the first question skips the second and everything hung
on the second.

Positions only, never words: a rule reads the same in every language.
The cabinet's dialog, the bot and the check of a sent answer all ask this
one function, so they cannot disagree about what was asked.
"""

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
    """The positions asked, in order, for these picks by position.

    ``picks`` holds the option positions picked on each choice question;
    a question with no entry has nothing picked.
    """
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
    """Why a rule cannot stand, as a short code, or ``""`` when it can.

    ``parent_options`` is how many options the parent question has, ``-1``
    when it is not a choice question. Codes: ``later`` - the parent is not
    before this question; ``kind`` - it is not a choice; ``options`` - no
    option, or one it does not have.
    """
    if not parent:
        return ""
    if parent >= position or parent < 1:
        return "later"
    if parent_options < 0:
        return "kind"
    if not options or any(not 0 <= option < parent_options for option in options):
        return "options"
    return ""
