"""Whether a change did what its rule expected."""

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
    """The verdict on one approved change, or ``None`` while it is too early."""
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
