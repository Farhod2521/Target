"""What was proposed before, as the review reads it beside tonight's list.

Each line is what the owner's history column already says: the change, what
the owner did with it, and - once the aftermath was read - the verdict and
the figure it was read from. One formatter for the figure, the one the card
uses, so the review and the history agree about what happened.

**For deciding, never for quoting.** Like the rates in
:mod:`apps.agent.steps`, these figures are not on tonight's card, so the
block stays out of what the reason may cite.
"""

from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from typing import Final

from app.modules.agent.aftermath import comparison
from app.modules.agent.constants import (
    RULE_LABELS,
    SuggestionKind,
    SuggestionOutcome,
    SuggestionStatus,
)
from app.modules.agent.models import AgentSuggestion
from core.agent import Finding

RECENT_DAYS: Final = 14
MONTH_DAYS: Final = 45


def past_block(
    *,
    findings: list[Finding],
    past: Mapping[str, Sequence[AgentSuggestion]],
    now: datetime,
    currency: str,
) -> str:
    """``## What was proposed before`` with one part per entry, or ``""``.

    An advert's part carries its group's proposals too: a budget moved on
    the group is the history of every advert in it.
    """
    parts = []
    for index, finding in enumerate(findings):
        rows = [*past.get(finding.ref.id, ())]
        if finding.parent_id:
            rows += past.get(finding.parent_id, ())
        if rows:
            lines = "\n".join(
                f"- {past_line(row, now=now, currency=currency)}" for row in rows
            )
            parts.append(f"### {index}\n{lines}")
    if not parts:
        return ""
    return "## What was proposed before\n\n" + "\n\n".join(parts)


def past_line(row: AgentSuggestion, *, now: datetime, currency: str) -> str:
    """One proposal: how long ago, what, what the owner did, how it ended."""
    line = f"{_when(now - row.created_at)}: {SuggestionKind(row.kind).label} ({RULE_LABELS.get(row.rule, row.rule)}) - {SuggestionStatus(row.status).label}"
    if row.outcome:
        line += f". Natija: {SuggestionOutcome(row.outcome).label}"
        found = comparison(
            rule=row.rule,
            evidence=row.evidence,
            after=row.outcome_figures,
            currency=currency,
        )
        if found is not None:
            line += f" ({found.label}: {found.before} -> {found.after})"
    return line


def _when(age: timedelta) -> str:
    """How long ago, in words without a digit.

    A digit here would be a figure the reason could carry onto the card, and
    the gate passes a small one followed by "kun" as part of the sentence -
    so the model is never handed one to copy.
    """
    if age < timedelta(days=RECENT_DAYS):
        return "Yaqinda"
    if age < timedelta(days=MONTH_DAYS):
        return "Bir oycha oldin"
    return "Bir necha oy oldin"


__all__ = ["past_block", "past_line"]
