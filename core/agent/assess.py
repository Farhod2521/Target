"""Whether a change did what its rule expected.

The other half of the loop. A rule notices, an owner approves, a worker
writes; this module is what looks back afterwards: the same arithmetic
discipline as the rules, run against the days *after* the change,
answering the one question that makes an agent worth trusting - "you said
this would help; did it?"

**The expectation is not stored anywhere, and that is a decision.** What a
change promises follows from the rule that proposed it - a pause promises
the spending stops, a raise promises more qualified leads - so the promise
is a function of the rule code, written once in :mod:`core.agent.promises`,
rather than a copy on every row that could drift from the definition that
judges it. The numbers it is judged against are on the row already:
``evidence`` is overwritten at approval with the figures the decision was
actually made on.

**Directions and criteria, never forecasts.** No "about two leads a day":
that number would be a linear extrapolation wearing the confidence of a
measurement. What is recorded instead is falsifiable: which way the
figures should have moved, and whether they did.

**The aftermath is not always the object's own.** Eight of the nine changes
are graded on the thing that changed; switching one advert off is graded on
the group it sat in, because that is what it was meant to help and the
advert itself is guaranteed to be quiet afterwards. Which figures to read is
therefore the caller's decision, made from the rule - see
``apps.agent.services.assess_outcomes``.

No Django, no clock. The aftermath arrives as a value; ``None`` means "too
early to say", and what to do about that is the caller's question.
"""

from collections.abc import Mapping
from typing import Any

from core.agent.contracts import Aftermath, Verdict
from core.agent.promises import (
    CHECKS,
    EXPECTATIONS,
    GONE,
    NOT_WORKED,
    PARENT_PROMISES,
    UNCLEAR,
    WORKED,
    figures,
)

# The rules whose promise is about the object one level up. A set rather
# than a check inside the caller, so that "which figures does this verdict
# need" has one answer in the domain instead of a condition in a service.
JUDGED_ON_PARENT: frozenset[str] = frozenset(
    code for code, promise in EXPECTATIONS.items() if promise in PARENT_PROMISES
)


def assess(
    *,
    rule: str,
    evidence: Mapping[str, Any],
    after: Aftermath,
    min_days: int,
) -> Verdict | None:
    """The verdict on one approved change, or ``None`` while it is too early.

    ``after`` describes the full days since the change landed - never the
    standard window, which would average the new state with days from
    before it. ``min_days`` is the same evidence bar the rules use: a
    verdict needs as many days as an opinion did.

    An unknown rule answers ``UNCLEAR`` rather than raising: a rule retired
    after this row was written is history meeting newer code, and "we can
    no longer say" is the honest reading of that.
    """
    check = CHECKS.get(rule)
    if check is None:
        return Verdict(outcome=UNCLEAR, figures=figures(rule, after))
    return check(evidence=evidence, after=after, min_days=min_days)


__all__ = [
    "EXPECTATIONS",
    "GONE",
    "JUDGED_ON_PARENT",
    "NOT_WORKED",
    "UNCLEAR",
    "WORKED",
    "assess",
]
