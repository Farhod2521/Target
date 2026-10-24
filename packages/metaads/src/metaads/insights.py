"""Daily performance, as Meta reports it."""

import json
import re
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from typing import Any, Final

from metaads.client import GraphClient
from metaads.errors import MetaAPIError

INSIGHT_FIELDS: Final = (
    "date_start,date_stop,account_currency,"
    "campaign_id,campaign_name,adset_id,adset_name,ad_id,ad_name,"
    "spend,impressions,reach,clicks,frequency,ctr,cpm,cpc,actions,"
    "unique_clicks,inline_link_clicks,unique_inline_link_clicks,"
    "outbound_clicks,"
    "cost_per_action_type,action_values,"
    "video_play_actions,video_thruplay_watched_actions,"
    "video_p25_watched_actions,video_p50_watched_actions,"
    "video_p75_watched_actions,video_p100_watched_actions,"
    "estimated_ad_recallers,"
    "attribution_setting,"
    "optimization_goal"
)

ATTRIBUTION_WINDOWS: Final[tuple[str, ...]] = ("7d_click", "1d_view")

ATTRIBUTION_ASKED: Final = "_".join(ATTRIBUTION_WINDOWS)

_NEXT_WINDOW: Final = re.compile(r"_(?=\d)")


def _windows(setting: str) -> frozenset[str]:
    """The windows in one of Meta's joined settings, order thrown away."""
    return frozenset(_NEXT_WINDOW.split(setting))


def differing_attribution(setting: object) -> str:
    """The account's own attribution window, but only if it is not ours."""
    found = str(setting or "").strip()
    if not found or found == "default":
        return ""
    if _windows(found) == frozenset(ATTRIBUTION_WINDOWS):
        return ""
    return found


AD_RANKING_FIELDS: Final = (
    "quality_ranking,engagement_rate_ranking,conversion_rate_ranking"
)

RANKED_LEVEL: Final = "ad"

PAGE_SIZE: Final = 500

MAX_INSIGHT_PAGES: Final = 200

LEAD_ACTIONS: Final[tuple[str, ...]] = (
    "onsite_conversion.lead_grouped",
    "leadgen_grouped",
    "lead",
    "offsite_conversion.fb_pixel_lead",
)

WEBSITE_LEAD_ACTIONS: Final[tuple[str, ...]] = (
    "lead",
    "offsite_conversion.fb_pixel_lead",
)

WEBSITE_GOALS: Final = frozenset({"OFFSITE_CONVERSIONS"})

RESULT_ACTIONS: Final[tuple[str, ...]] = (
    "onsite_conversion.messaging_conversation_started_7d",
    "onsite_conversion.total_messaging_connection",
    "click_to_call_native_call_placed",
    "click_to_call_call_confirm",
)

RESULTS_FIELD: Final = "results"
PROFILE_VISIT_INDICATORS: Final = frozenset(
    {"profile_visit_view", "total_profile_visits"}
)
ACTION_INDICATOR: Final = "actions:"
DEFAULT_WINDOW: Final = "default"
_INVALID_PARAMETER: Final = 100

OUTBOUND_ACTION: Final = "outbound_click"

REACTION_ACTIONS: Final[tuple[str, ...]] = ("post_reaction",)
COMMENT_ACTIONS: Final[tuple[str, ...]] = ("comment",)
SHARE_ACTIONS: Final[tuple[str, ...]] = ("post",)
SAVE_ACTIONS: Final[tuple[str, ...]] = ("onsite_conversion.post_save",)

LANDING_PAGE_ACTIONS: Final[tuple[str, ...]] = ("landing_page_view",)
VIDEO_VIEW_ACTIONS: Final[tuple[str, ...]] = ("video_view",)


def fetch_insights(
    *,
    account_id: str,
    since: date,
    until: date,
    level: str,
    token: str,
    client: GraphClient | None = None,
) -> list[dict[str, Any]]:
    """Every day in the range, one row per object per day."""
    with _session(client, token) as graph:
        try:
            return _read_days(
                graph,
                account_id=account_id,
                fields=f"{fields_for(level)},{RESULTS_FIELD}",
                level=level,
                since=since,
                until=until,
            )
        except MetaAPIError as exc:
            if type(exc) is not MetaAPIError or exc.code != _INVALID_PARAMETER:
                raise
            return _read_days(
                graph,
                account_id=account_id,
                fields=fields_for(level),
                level=level,
                since=since,
                until=until,
            )


def _read_days(
    graph: GraphClient,
    *,
    account_id: str,
    fields: str,
    level: str,
    since: date,
    until: date,
) -> list[dict[str, Any]]:
    """One insights read, a row per object per day."""
    return list(
        graph.get_all(
            f"{account_id}/insights",
            fields=fields,
            level=level,
            time_increment=1,
            time_range=as_time_range(since=since, until=until),
            action_attribution_windows=json.dumps(list(ATTRIBUTION_WINDOWS)),
            limit=PAGE_SIZE,
            max_pages=MAX_INSIGHT_PAGES,
        )
    )


PEOPLE_FIELDS: Final = (
    "date_start,date_stop,campaign_id,adset_id,ad_id,reach,estimated_ad_recallers"
)


def fetch_people_counts(
    *,
    account_id: str,
    ranges: list[tuple[date, date]],
    level: str,
    token: str,
    client: GraphClient | None = None,
) -> list[dict[str, Any]]:
    """Reach and the ad recall estimate over whole ranges, one row per range."""
    with _session(client, token) as graph:
        return list(
            graph.get_all(
                f"{account_id}/insights",
                fields=PEOPLE_FIELDS,
                level=level,
                time_ranges=json.dumps(
                    [
                        {"since": since.isoformat(), "until": until.isoformat()}
                        for since, until in ranges
                    ]
                ),
                limit=PAGE_SIZE,
                max_pages=MAX_INSIGHT_PAGES,
            )
        )


def fetch_action_totals(
    *,
    account_id: str,
    since: date,
    until: date,
    token: str,
    client: GraphClient | None = None,
) -> list[dict[str, Any]]:
    """Every action type the account reported over a range, as Meta sent it."""
    with _session(client, token) as graph:
        rows = list(
            graph.get_all(
                f"{account_id}/insights",
                fields="actions",
                level="account",
                time_range=as_time_range(since=since, until=until),
                action_attribution_windows=json.dumps(list(ATTRIBUTION_WINDOWS)),
                limit=PAGE_SIZE,
            )
        )
    return [
        entry
        for row in rows
        for entry in (row.get("actions") or [])
        if isinstance(entry, dict)
    ]


def fields_for(level: str) -> str:
    """What to ask for at one level."""
    if level == RANKED_LEVEL:
        return f"{INSIGHT_FIELDS},{AD_RANKING_FIELDS}"
    return INSIGHT_FIELDS


def action_value(entries: object, names: tuple[str, ...]) -> str:
    """The first of ``names`` this array reports, as Meta sent it."""
    if not isinstance(entries, list):
        return ""

    by_type = {
        str(row.get("action_type", "")): row.get("value")
        for row in entries
        if isinstance(row, dict)
    }
    for name in names:
        if name in by_type:
            value = by_type[name]
            return "" if value is None else str(value)
    return ""


def lead_actions_for(goal: object) -> tuple[str, ...]:
    """Which ``actions`` names count as a lead for a row with this goal."""
    return WEBSITE_LEAD_ACTIONS if goal in WEBSITE_GOALS else LEAD_ACTIONS


def lead_count(actions: object, *, goal: object) -> int:
    """How many leads one row reports, whatever Meta called them."""
    return _as_int(action_value(actions, lead_actions_for(goal)))


def result_count(actions: object) -> int:
    """How many results of a kind this product holds no table for."""
    return _as_int(action_value(actions, RESULT_ACTIONS))


def meta_result_count(results: object) -> int | None:
    """Ads Manager's "Results" for one row, where it can be added up."""
    if not isinstance(results, list):
        return None
    for entry in results:
        if not isinstance(entry, dict):
            continue
        indicator = str(entry.get("indicator", ""))
        values = entry.get("values")
        if values and (
            indicator.startswith(ACTION_INDICATOR)
            or indicator in PROFILE_VISIT_INDICATORS
        ):
            return result_value(values)
    return None


def profile_visit_count(results: object) -> int:
    """How many Instagram profile visits one row reports, from ``results``."""
    if not isinstance(results, list):
        return 0
    for entry in results:
        if (
            isinstance(entry, dict)
            and entry.get("indicator") in PROFILE_VISIT_INDICATORS
        ):
            return result_value(entry.get("values")) or 0
    return 0


def result_value(values: object) -> int | None:
    """The count Ads Manager prints, out of one ``results`` entry's values."""
    if not isinstance(values, list):
        return None
    entries = [row for row in values if isinstance(row, dict)]
    for row in entries:
        if DEFAULT_WINDOW in (row.get("attribution_windows") or ()):
            return _as_int(row.get("value"))
    for row in entries:
        if not row.get("attribution_windows"):
            return _as_int(row.get("value"))
    return None


def action_count(entries: object, names: tuple[str, ...]) -> int:
    """The first of ``names`` this array reports, as a whole number."""
    return _as_int(action_value(entries, names))


def single_value(entries: object) -> int:
    """The count out of one of Meta's single-entry arrays."""
    if not isinstance(entries, list):
        return 0
    for row in entries:
        if isinstance(row, dict):
            return _as_int(row.get("value"))
    return 0


def as_time_range(*, since: date, until: date) -> str:
    """``time_range`` as Meta takes it: a JSON object in a query string."""
    return json.dumps({"since": since.isoformat(), "until": until.isoformat()})


def _as_int(value: object) -> int:
    """Meta sends counts as strings, and sometimes as decimal ones."""
    if value is None:
        return 0
    try:
        return int(float(str(value)))
    except (TypeError, ValueError):
        return 0


@contextmanager
def _session(client: GraphClient | None, token: str) -> Iterator[GraphClient]:
    """One connection, closed only if this module opened it."""
    graph = client or GraphClient(token=token)
    try:
        yield graph
    finally:
        if client is None:
            graph.close()
