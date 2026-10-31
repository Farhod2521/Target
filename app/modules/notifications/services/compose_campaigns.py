"""A campaign's line, as the weekly message prints it: what it spent, what it
brought, what one cost against the usual, and the cause the night found."""

from collections.abc import Mapping
from typing import Final

from app.modules.notifications.services.compose import _bold, _italic, escaped
from core.chat.daily import NO_FIGURE, Census, DayCampaign

SEPARATOR: Final = " · "


def census_lines(census: Census) -> list[str]:
    if census.spenders < 2:
        return []
    ran = "%(count)d ta kampaniya ishladi" % {"count": census.spenders}
    if census.all_fine:
        return ["", escaped(f"{ran} — {'hammasi joyida'}")]
    parts = []
    if census.fine:
        parts.append("%(count)d joyida" % {"count": census.fine})
    if census.watch:
        parts.append("%(count)d kuzatishda" % {"count": census.watch})
    if census.burning:
        parts.append("%(count)d pul yoqyapti" % {"count": census.burning})
    return ["", escaped(f"{ran}: {', '.join(parts)}")]


def attention_lines(
    rows: tuple[DayCampaign, ...],
    *,
    usual: str = "",
    said: Mapping[DayCampaign, str] | None = None,
) -> list[str]:
    if not rows:
        return []
    lines = ["", _bold("E'tibor talab qiladi")]
    for row in rows:
        lines.append(campaign_row(row, usual=usual))
        if row.cause_label:
            lines.append(_italic(cause_said(row)))
        if line := (said or {}).get(row, ""):
            lines.append(escaped(line))
    return lines


def campaign_row(row: DayCampaign, *, usual: str = "") -> str:
    return f"{_bold(f'«{row.name}»')} — {escaped(_outcome(row, usual=usual))}"


def _outcome(row: DayCampaign, *, usual: str) -> str:
    parts = [row.spend]
    if row.kind != "none":
        if row.results == 0:
            parts.append("natija yo'q")
        else:
            parts.append(f"{row.result_label}: {row.results}")
            if row.cost != NO_FIGURE:
                said = row.cost
                if row.usual_cost != NO_FIGURE:
                    said += (
                        f" ({usual % {'value': row.usual_cost}})"
                        if usual
                        else f" ({'odatda'} {row.usual_cost})"
                    )
                parts.append(said)
    if row.learning:
        parts.append("o'rganmoqda")
    return SEPARATOR.join(parts)


def cause_said(row: DayCampaign) -> str:
    if not row.cause_line:
        return row.cause_label
    if row.cause_line.startswith(row.cause_label):
        return row.cause_line
    return f"{row.cause_label} — {row.cause_line}"


__all__ = ["attention_lines", "campaign_row", "cause_said", "census_lines"]
