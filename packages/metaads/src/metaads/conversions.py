"""Telling Meta how a lead turned out.

The only module in this package that sends Meta something it did not send
us first, and the reason the whole product's headline figure can act on
anything. Meta delivers a lead and knows one fact about it - that a form
was submitted - so an account left to itself is optimised towards
submissions. Whether the telephone was answered by a customer or by nobody
is known here and nowhere else, and until it is sent back, the platform
buying the leads and the screen judging them are measuring different things.

Three of Meta's rules shape everything below.

* **The lead is named by Meta's own id.** A CRM event carries
  ``user_data.lead_id`` - the ``leadgen_id`` that arrived with the webhook -
  and nothing else about the person. No email, no telephone, not even a
  hash of one. This module cannot leak personal data because it is never
  given any; contrast :mod:`metaads.customer_lists`, which is the other
  direction of the same boundary and carries digests.
* **The event name is the advertiser's own.** Meta does not publish a fixed
  vocabulary for lead stages: an event is sent under whatever name the
  advertiser chose, and a custom conversion is then defined against that
  name in Ads Manager. So the names below are **this product's** words, and
  they have to match the custom conversion somebody set up - which is why
  they are constants here rather than strings at a call site.
* **``action_source`` is ``system_generated``.** The person did not do
  anything; a system decided something about them afterwards. Meta reads a
  browser source as a website event and asks for a click id we do not have.

The window is Meta's, not ours: an event older than
:data:`REPORT_WINDOW_DAYS` is accepted with a 200 and silently not counted,
which is the worst possible failure shape - so callers ask for the window
before they build a batch rather than reading it out of the answer.
"""

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

# Meta's own edge for server-side events. A dataset id, which is the same
# number an advertiser still calls a pixel id - Meta renamed the object and
# kept the id space.
EVENTS_EDGE: Final = "events"

# What Meta is told about where the event came from. Not ``website`` and
# not ``app``: nobody browsed anything. Meta's own value for "our systems
# decided this", and the one that does not demand a click identifier.
ACTION_SOURCE: Final = "system_generated"

# How this product names each verdict when it sends one.
#
# **These strings are a contract with a custom conversion Meta holds**, not
# with an API. Changing one here without changing the custom conversion in
# Ads Manager does not fail: the events keep arriving, under a name nothing
# is counting, and the optimiser goes on learning from the old ones until
# they age out. Which is why they are frozen constants with this note
# attached rather than anything derived.
#
# Prefixed, and that is the point of the prefix. An account may already
# have a ``Lead`` or a ``Purchase`` event arriving from a website pixel,
# and a name collision would merge two populations that mean different
# things into one conversion.
STAGE_EVENTS: Final[dict[LeadStage, str]] = {
    "qualified": "TargetologAIQualifiedLead",
    "unqualified": "TargetologAIDisqualifiedLead",
    "converted": "TargetologAIConvertedLead",
}

# How far back Meta will still count a server event. Seven days is Meta's
# published limit for events sent to a dataset, and the number is here
# rather than in the domain because it is a provider's rule - see
# ``ConversionPort.report_window_days``.
REPORT_WINDOW_DAYS: Final = 7

# Meta's cap on one request. A longer list is split here rather than by the
# caller, exactly as a customer list is: a caller splitting it would be a
# caller that had learned Meta's batching rules.
MAX_EVENTS_PER_CALL: Final = 1_000


def report_leads(
    *,
    dataset_id: str,
    events: Sequence[LeadEventDTO],
    token: str,
    client: GraphClient | None = None,
    dry_run: bool = True,
) -> ConversionReceiptRow:
    """Send a batch of verdicts to one dataset. Returns what Meta took.

    Nothing is sent for an empty list and nothing is sent in a dry run,
    and both answer nought accepted rather than raising. An empty batch is
    the ordinary result of a sweep that found nothing to do, and a caller
    made to branch on it would branch on it in four places.

    The counts of several requests are summed. Meta answers each one
    separately and a partial failure raises, which means a long list is
    all-or-nothing per request and the caller retries the whole sweep -
    safe because every event carries an id Meta de-duplicates on.
    """
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
    """One verdict, in the shape Meta reads a server event in.

    ``event_time`` is whole seconds since the epoch, which is the only
    format this edge takes. The datetime arrives timezone-aware from the
    domain - the caller has a clock and this package does not - so the
    conversion needs no zone of its own.

    ``custom_data`` appears only on a sale. Meta reads ``value`` and
    ``currency`` as a pair and refuses one without the other, and the DTO
    has already refused an amount on any other stage.
    """
    payload: dict[str, Any] = {
        "event_name": event_name(item.stage),
        "event_time": int(item.occurred_at.timestamp()),
        "event_id": item.event_id,
        "action_source": ACTION_SOURCE,
        # The whole of what Meta is told about the person: the id it issued
        # when it handed them over. Nested because ``user_data`` is where
        # Meta looks for identity, and this is the one identifier in it
        # that is not a digest of something somebody typed.
        "user_data": {"lead_id": item.lead.id},
    }
    if item.value_minor is not None:
        payload["custom_data"] = {
            # Meta takes a major-unit amount here, which is the one place
            # in this package that a minor-unit integer has to be divided.
            # Done with the provider's own decimal places rather than a
            # blanket hundred - see ``metaads.money``.
            "value": _major(item.value_minor, item.currency),
            "currency": item.currency.upper(),
        }
    return payload


def _major(amount_minor: int, currency: str) -> str:
    """A minor-unit integer as the decimal string Meta wants.

    A string rather than a float, deliberately. This is the only division
    in the package and the result travels through JSON; a float would
    reintroduce, at the last possible moment, exactly the imprecision the
    minor-unit rule exists to prevent.
    """
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
