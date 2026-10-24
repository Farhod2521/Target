"""The first step's table, written out for the model that reads the owner's words."""

from collections.abc import Mapping, Sequence
from typing import Final

from core.targeting.compat import OUTCOMES, Offer

OUTCOME_NAMES: Final[dict[str, str]] = {
    "requests": "A request - the customer leaves a name and phone number",
    "calls": "A phone call",
    "messages": "A message in a chat",
    "visits": "A visit to the website",
    "profile": "A visit to the business's own Instagram profile",
    "reach": "Being seen - nothing is asked of the customer",
    "sales": "An online sale",
}


def render_rows(
    *,
    offers: Sequence[Offer],
    defaults: frozenset[str],
    closed: Mapping[str, str],
) -> str:
    """The rows as Markdown, grouped by outcome in the screen's order."""
    lines: list[str] = []
    for spec in OUTCOMES:
        rows = [row for row in offers if row.outcome == spec.key]
        if not rows:
            continue
        lines.append(f"### {OUTCOME_NAMES.get(spec.key, spec.key)}")
        lines.append("")
        lines.extend(_row_lines(row, defaults=defaults, closed=closed) for row in rows)
        lines.append("")
    return "\n".join(lines).strip()


def _row_lines(
    row: Offer, *, defaults: frozenset[str], closed: Mapping[str, str]
) -> str:
    meta = " · ".join(
        part
        for part in (
            row.kind.provider_label,
            row.provider_destination_label,
            row.kind.provider_goal_label,
        )
        if part
    )
    marks = [meta]
    if row.key in defaults:
        marks.append("default")
    if row.key in closed:
        marks.append(f"to'sqin: {closed[row.key]}")
    said = ", ".join(f'"{phrase}"' for phrase in row.phrases)
    return f"- `{row.key}` ({'; '.join(marks)})\n  {row.meaning}\n  Owners say: {said}."


__all__ = ["OUTCOME_NAMES", "render_rows"]
