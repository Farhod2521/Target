"""ChatGPT Ads figures as :class:`adskit.MetricsPort`, from ``/ad_account/insights``.

One report per question, scoped to the key's account: ``aggregation_level``
picks the row (campaign, ad group, ad) and ``time_granularity`` the bucket.
Dates go as a ``date_range`` in the account's own timezone, ``until``
inclusive - the port's own convention.

Spend arrives as a decimal of the account currency, not in micros. OpenAI
counts no leads; its conversions land in ``results_reported``.
"""

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any, Final

import httpx
from adskit.dto import MetricsDTO, PeopleCountDTO, SegmentMetricsDTO
from adskit.errors import InvalidRequest
from adskit.refs import BreakdownKind, ExternalRef, Level, MinorUnits

from openaiadskit.accounts import read_ad_account
from openaiadskit.campaigns import openai_calls
from openaiadskit.client import AdsClient
from openaiadskit.rows import PROVIDER, amount_to_minor, ref

# Our level name and OpenAI's for a report row.
_ROWS: Final[dict[str, str]] = {
    "campaign": "campaign",
    "adset": "ad_group",
    "ad": "ad",
}
# Conversions are not asked for: they need a conversion event set up, and
# a field the account cannot report would refuse the whole report. A row
# that carries them anyway is read.
_METRICS: Final = ("impressions", "clicks", "spend")
_REPORT_PAGE: Final = 2000


@dataclass(frozen=True, slots=True)
class Totals:
    """One object's figures summed over a range."""

    impressions: int
    clicks: int
    spend_minor: MinorUnits
    conversions: int


def _row_level(level: Level) -> str:
    found = _ROWS.get(level)
    if found is None:
        raise InvalidRequest(f"{PROVIDER} reports no {level!r} rows")
    return found


def _report(
    client: AdsClient, *, since: date, until: date, level: Level, granularity: str
) -> list[dict[str, Any]]:
    row = _row_level(level)
    fields = [f"{row}.id", f"{row}.name"] + [f"{row}.{m}" for m in _METRICS]
    if granularity != "none":
        fields.append("metadata.readable_time")
    span = {
        "type": "date_range",
        "since": since.isoformat(),
        "until": until.isoformat(),
    }
    params: dict[str, str | int | list[str]] = {
        "aggregation_level": row,
        "time_granularity": granularity,
        "time_ranges": [json.dumps(span)],
        "fields": fields,
        "limit": _REPORT_PAGE,
    }
    return list(client.pages("ad_account/insights", params))


def report_totals(
    client: AdsClient, *, since: date, until: date, level: Level, currency: str
) -> dict[str, Totals]:
    """Each object's figures over the range, on a client the caller holds."""
    row = _row_level(level)
    rows = _report(client, since=since, until=until, level=level, granularity="none")
    return {
        str(item.get(f"{row}_id")): Totals(
            impressions=int(item.get("impressions") or 0),
            clicks=int(item.get("clicks") or 0),
            spend_minor=amount_to_minor(item.get("spend"), currency),
            conversions=int(item.get("conversions") or 0),
        )
        for item in rows
        if item.get(f"{row}_id")
    }


class OpenAIMetrics:
    """Daily rows for the port; summed rows for a screen's period."""

    def __init__(self, *, http: httpx.Client | None = None) -> None:
        self._http = http

    def fetch_daily(
        self,
        *,
        account: ExternalRef,
        since: date,
        until: date,
        level: Level,
        token: str,
    ) -> list[MetricsDTO]:
        row = _row_level(level)
        with openai_calls(), AdsClient(api_key=token, http=self._http) as client:
            currency = read_ad_account(client).currency
            rows = _report(
                client, since=since, until=until, level=level, granularity="daily"
            )
        found: list[MetricsDTO] = []
        for item in rows:
            object_id = str(item.get(f"{row}_id") or "")
            day = str(item.get("readable_time") or "")[:10]
            if not object_id or not day:
                continue
            found.append(
                MetricsDTO(
                    ref=ref(level, object_id),
                    day=date.fromisoformat(day),
                    campaign_external_id=object_id if level == "campaign" else "",
                    adset_external_id=object_id if level == "adset" else "",
                    ad_external_id=object_id if level == "ad" else "",
                    spend_minor=amount_to_minor(item.get("spend"), currency),
                    currency=currency,
                    impressions=int(item.get("impressions") or 0),
                    clicks=int(item.get("clicks") or 0),
                    results_reported=int(item.get("conversions") or 0),
                )
            )
        return found

    def fetch_totals(
        self, *, since: date, until: date, level: Level, token: str
    ) -> tuple[str, dict[str, Totals]]:
        """Each object's figures over the range, and the account currency."""
        with openai_calls(), AdsClient(api_key=token, http=self._http) as client:
            currency = read_ad_account(client).currency
            found = report_totals(
                client, since=since, until=until, level=level, currency=currency
            )
        return currency, found

    def fetch_breakdown(
        self,
        *,
        account: ExternalRef,
        since: date,
        until: date,
        level: Level,
        kind: BreakdownKind,
        token: str,
    ) -> list[SegmentMetricsDTO]:
        # Empty rather than refused, as Google's is: a nightly sync that
        # asks for every kind must not report this provider as failing.
        return []

    def fetch_people(
        self,
        *,
        account: ExternalRef,
        ranges: Sequence[tuple[date, date]],
        level: Level,
        token: str,
    ) -> list[PeopleCountDTO]:
        # OpenAI reports no reach; the port's contract is to answer nothing.
        return []


__all__ = ["OpenAIMetrics", "Totals", "report_totals"]
