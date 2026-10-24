"""Telling Meta how a lead turned out."""

import json
from collections.abc import Sequence
from typing import Any, Final

from adskit.dto import LeadEventDTO
from adskit.refs import LeadStage

from metaads.client import GraphClient
from metaads.dto import ConversionReceiptRow
from metaads.money import META_MONEY
from metaads.parsing import parsed
from metaads.writing import graph_client

EVENTS_EDGE: Final = "events"

ACTION_SOURCE: Final = "system_generated"

STAGE_EVENTS: Final[dict[LeadStage, str]] = {
    "qualified": "TargetologAIQualifiedLead",
    "unqualified": "TargetologAIDisqualifiedLead",
    "converted": "TargetologAIConvertedLead",
}

REPORT_WINDOW_DAYS: Final = 7

MAX_EVENTS_PER_CALL: Final = 1_000


def report_leads(
    *,
    dataset_id: str,
    events: Sequence[LeadEventDTO],
    token: str,
    client: GraphClient | None = None,
    dry_run: bool = True,
) -> ConversionReceiptRow:
    """Send a batch of verdicts to one dataset. Returns what Meta took."""
    payloads = [_event(item) for item in events]
    if not payloads or dry_run:
        return ConversionReceiptRow(events_received=0)

    accepted = 0
    trace = ""
    with graph_client(client, token) as graph:
        for batch in _batched(payloads):
            answer = graph.post(
                f"{dataset_id}/{EVENTS_EDGE}",
                data=json.dumps(batch, ensure_ascii=False),
            )
            row = parsed(ConversionReceiptRow, answer)
            accepted += row.events_received
            trace = row.fbtrace_id or trace

    return ConversionReceiptRow(events_received=accepted, fbtrace_id=trace)


def event_name(stage: LeadStage) -> str:
    """What this product calls one verdict when Meta is told about it."""
    return STAGE_EVENTS[stage]


def _event(item: LeadEventDTO) -> dict[str, Any]:
    """One verdict, in the shape Meta reads a server event in."""
    payload: dict[str, Any] = {
        "event_name": event_name(item.stage),
        "event_time": int(item.occurred_at.timestamp()),
        "event_id": item.event_id,
        "action_source": ACTION_SOURCE,
        "user_data": {"lead_id": item.lead.id},
    }
    if item.value_minor is not None:
        payload["custom_data"] = {
            "value": _major(item.value_minor, item.currency),
            "currency": item.currency.upper(),
        }
    return payload


def _major(amount_minor: int, currency: str) -> str:
    """A minor-unit integer as the decimal string Meta wants."""
    places = META_MONEY.decimal_places(currency)
    if places == 0:
        return str(amount_minor)
    scale = 10**places
    return f"{amount_minor // scale}.{amount_minor % scale:0{places}d}"


def _batched(payloads: list[dict[str, Any]]) -> list[list[dict[str, Any]]]:
    """Meta's cap, applied here so no caller has to know it."""
    return [
        payloads[start : start + MAX_EVENTS_PER_CALL]
        for start in range(0, len(payloads), MAX_EVENTS_PER_CALL)
    ]
