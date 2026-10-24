"""Reading one lead, reading the ones a webhook never delivered, and asking
to be told about the next."""

from collections.abc import Iterable
from datetime import datetime
from typing import Any, Final

from metaads.client import GraphClient
from metaads.dto import LeadRow
from metaads.parsing import parsed, parsed_all
from metaads.writing import encode, post_object

LEAD_FIELDS: Final = (
    "id,created_time,field_data,form_id,campaign_id,adset_id,ad_id,is_organic"
)

LEADGEN_FIELD: Final = "leadgen"

PAGE_SIZE: Final = 100

_SUCCESS: Final = "success"


def fetch_lead(
    *, leadgen_id: str, token: str, client: GraphClient | None = None
) -> LeadRow:
    """One lead, by the id a webhook named."""
    graph = client or GraphClient(token=token)
    try:
        return parsed(LeadRow, graph.get(leadgen_id, fields=LEAD_FIELDS))
    finally:
        if client is None:
            graph.close()


def list_leads(
    *,
    form_id: str,
    since: datetime,
    token: str,
    client: GraphClient | None = None,
    until: datetime | None = None,
) -> list[LeadRow]:
    """Every lead this form collected since ``since``, and before ``until``."""
    graph = client or GraphClient(token=token)
    try:
        rows: Iterable[dict[str, Any]] = graph.get_all(
            f"{form_id}/leads",
            fields=LEAD_FIELDS,
            filtering=_window(since, until),
            limit=PAGE_SIZE,
        )
        return parsed_all(LeadRow, rows)
    finally:
        if client is None:
            graph.close()


def subscribe_page(
    *,
    page_id: str,
    token: str,
    client: GraphClient | None = None,
    dry_run: bool = True,
) -> bool:
    """Ask Meta to send this page's leads to our webhook."""
    if dry_run:
        return True

    payload = post_object(
        path=f"{page_id}/subscribed_apps",
        data={"subscribed_fields": LEADGEN_FIELD},
        token=token,
        client=client,
    )
    return bool(payload.get(_SUCCESS, True))


def _window(since: datetime, until: datetime | None) -> str:
    """Meta's filter syntax for "created after this, and before that", as JSON."""
    clauses: list[dict[str, Any]] = [
        {
            "field": "time_created",
            "operator": "GREATER_THAN",
            "value": int(since.timestamp()),
        }
    ]
    if until is not None:
        clauses.append(
            {
                "field": "time_created",
                "operator": "LESS_THAN",
                "value": int(until.timestamp()),
            }
        )
    return str(encode(clauses))


__all__ = [
    "LEADGEN_FIELD",
    "LEAD_FIELDS",
    "fetch_lead",
    "list_leads",
    "subscribe_page",
]
