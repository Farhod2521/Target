"""Reading one lead, reading the ones a webhook never delivered, and asking
to be told about the next.

Three calls, and the third is the one that is easy to leave out and
impossible to notice missing. ``POST /{page_id}/subscribed_apps`` is what
makes Meta send the webhook at all: without it a form fills in, the person
who filled it waits for a call, and nothing arrives anywhere - no error, no
lead, no clue why.

The order the other two are used in matters and is decided above this
package: a webhook is stored before :func:`fetch_lead` is called, because
Meta not answering must cost a retry rather than the lead.

Reading a lead is subject to a limit of its own -
``200 x 24 x (leads created in the last 90 days)`` per page per day - which
is generous while the webhook is the main path and easy to exhaust by
polling. :func:`list_leads` is the reconciliation sweep, not a substitute.
Meta drops a lead ninety days after it is submitted, which is why that
sweep runs daily rather than being an optimisation: a lead the webhook
missed is recoverable for a season, not forever.
"""

from collections.abc import Iterable
from datetime import datetime
from typing import Any, Final

from metaads.client import GraphClient
from metaads.dto import LeadRow
from metaads.parsing import parsed, parsed_all
from metaads.writing import encode, post_object

# Everything a lead is. ``adgroup_id`` is absent because the Graph read
# spells it ``adset_id`` - only the webhook payload uses the other name,
# and that arrives already parsed rather than asked for.
LEAD_FIELDS: Final = (
    "id,created_time,field_data,form_id,campaign_id,adset_id,ad_id,is_organic"
)

# The webhook field being subscribed to. One string, and the reason this
# module exists: Meta's page subscription is per field, and a page
# subscribed to everything except this one looks healthy and delivers no
# leads.
LEADGEN_FIELD: Final = "leadgen"

# Meta's own maximum for the leads edge. Fewer, larger pages is fewer calls
# against a limit that is counted per page rather than per app.
PAGE_SIZE: Final = 100

_SUCCESS: Final = "success"


def fetch_lead(
    *, leadgen_id: str, token: str, client: GraphClient | None = None
) -> LeadRow:
    """One lead, by the id a webhook named.

    The page's token, not the ad account's. A lead belongs to the form,
    the form belongs to the page, and the account's token is refused here
    with a permission error that names the lead and not the reason.
    """
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
    """Every lead this form collected since ``since``, and before ``until``.

    The reconciliation path. A webhook that was never delivered - a
    deployment window, a signature we rejected, a page whose subscription
    lapsed - leaves no trace anywhere, so the only way to find out is to
    ask. Meta keeps leads for ninety days, which is the ceiling on how far
    back this can ever recover.

    ``since`` is passed as a filter rather than read from a clock: this
    package has none, and the caller knows when it last succeeded.
    ``until`` is the other end, for a caller narrowing a window that was
    too deep to read in one go; ``None`` leaves it open.
    """
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
    """Ask Meta to send this page's leads to our webhook.

    Idempotent at Meta's end: subscribing a page that is already
    subscribed answers success and changes nothing, which is why this can
    be called every time a page is chosen rather than tracked as a
    one-off.

    The page's own token again, and the reason is the same. This is also
    the one call in the package that needs ``pages_manage_metadata`` - a
    permission nothing else here justifies asking for.
    """
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
    """Meta's filter syntax for "created after this, and before that", as JSON.

    A list of clauses, because the parameter takes a list and a bare
    object is refused with an error about the field rather than the shape.
    ``GREATER_THAN`` on a unix timestamp: the edge accepts an ISO string
    too and compares it as *text*, which silently returns everything. The
    closing clause is only sent when there is an end to close.

    Encoded here rather than handed over as a list. A query parameter is
    stringified by the HTTP client, and Python's repr of a dict uses single
    quotes - which Meta rejects with an error naming the field and not the
    reason.
    """
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
