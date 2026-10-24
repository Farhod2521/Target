"""The same day's figures, cut into segments instead of summed.

The endpoint is the one :mod:`metaads.insights` uses, asked a second
question. ``breakdowns=["age","gender"]`` makes Meta answer one row per
slice per object per day - and **stop answering the summary row**. The two
never come back together, which is why this is a separate call rather than
a wider field list on the existing one.

Three things about it are worth knowing before reading the code.

**It is the expensive call, and how expensive depends on the cut.** Age and
gender are seven buckets by three genders, so one ad set's day becomes up to
twenty-one rows where the summary had one. Platform and position is the
cheaper of the two - a position only exists on the platform that offers it,
so the pairs are a short list rather than a product, and an ad set delivers
to a handful of them. Paging is where a rate limit is actually spent, and a
ninety-day range at the wider width is dozens of round trips against a budget
shared with lead retrieval. Which days to ask for is therefore the caller's
decision and not a default here.

**It asks for counts and nothing else.** Spend, impressions, reach, clicks
and the lead count buried in ``actions``. No names, no rankings, no video,
no ratios - every ratio is arithmetic on the counts above it, and a stored
ratio is the figure somebody eventually averages across days, which is
always wrong. What the object was called is already on its summary row.

**The attribution window is the same one.** Sent explicitly, from the same
constant the summary request uses. A segment's lead count resting on a
different window than the total it is compared against is a discrepancy
nobody would think to look for.
"""

import json
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from typing import Any, Final

from metaads.client import GraphClient
from metaads.insights import (
    ATTRIBUTION_WINDOWS,
    MAX_INSIGHT_PAGES,
    PAGE_SIZE,
    as_time_range,
)

# What one segment row has to carry.
#
# Eleven fields where the summary asks for thirty-two, and the difference is
# the point. Everything dropped is either already on the summary row for the
# same object and day, or is arithmetic on what is here: ``ctr`` is clicks
# over impressions, ``cpm`` is spend over impressions, ``frequency`` is
# impressions over reach. Asking a provider for its own copy of arithmetic
# we can do is asking for a second version of a number that can disagree
# with the first.
#
# ``frequency`` is the one worth naming, because on a placement cut it is a
# real signal rather than a redundant one: a story is shown to the same
# person far more often than a feed is, and a placement whose frequency is
# climbing is a creative wearing out in that placement. It is still not
# asked for. It is exactly ``impressions / reach``, and both are in the list
# above - so asking would buy a second copy of a division, and a copy that
# can disagree with ours on rounding. The division is done in the domain,
# **per row**: reach counts people, so a range's frequency is not something
# that can be recovered from a range's rows and is not offered.
#
# ``account_currency`` is not optional. Spend arrives in whole currency and
# only the account says which one, so the figure without it is a number with
# no unit.
#
# All three ids at every level: they are how a row is attributed, and an ad
# set's segments are read beside its campaign's totals.
BREAKDOWN_FIELDS: Final = (
    "date_start,date_stop,account_currency,"
    "campaign_id,adset_id,ad_id,"
    "spend,impressions,reach,clicks,actions,"
    # Not a figure: what decides which of the actions is a lead. See
    # ``insights.WEBSITE_LEAD_ACTIONS``.
    "optimization_goal"
)


def fetch_breakdown(
    *,
    account_id: str,
    since: date,
    until: date,
    level: str,
    breakdowns: tuple[str, ...],
    token: str,
    client: GraphClient | None = None,
) -> list[dict[str, Any]]:
    """Every day in the range at one level, split by ``breakdowns``.

    ``breakdowns`` travels as Meta's own parameter names - ``("age",
    "gender")`` - because the caller translating a domain word into them is
    the adapter, and this module is below it. The order is the order the
    parts come back in and therefore the order they are joined in, so it is
    part of the contract rather than a formatting detail.

    Returns raw rows. Each carries the breakdown keys as ordinary top-level
    fields beside the figures, which is Meta's shape and not something worth
    rearranging here.
    """
    with _session(client, token) as graph:
        return list(
            graph.get_all(
                f"{account_id}/insights",
                fields=BREAKDOWN_FIELDS,
                level=level,
                breakdowns=",".join(breakdowns),
                time_increment=1,
                time_range=as_time_range(since=since, until=until),
                action_attribution_windows=json.dumps(list(ATTRIBUTION_WINDOWS)),
                limit=PAGE_SIZE,
                max_pages=MAX_INSIGHT_PAGES,
            )
        )


@contextmanager
def _session(client: GraphClient | None, token: str) -> Iterator[GraphClient]:
    """One connection, closed only if this module opened it."""
    graph = client or GraphClient(token=token)
    try:
        yield graph
    finally:
        if client is None:
            graph.close()
