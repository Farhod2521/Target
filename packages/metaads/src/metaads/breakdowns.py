"""The same day's figures, cut into segments instead of summed."""

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

BREAKDOWN_FIELDS: Final = (
    "date_start,date_stop,account_currency,"
    "campaign_id,adset_id,ad_id,"
    "spend,impressions,reach,clicks,actions,"
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
    """Every day in the range at one level, split by ``breakdowns``."""
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
