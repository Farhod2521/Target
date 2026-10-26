"""Daily Google Ads figures as :class:`adskit.MetricsPort`.

One GAQL read per level, segmented by date. ``segments.date`` is the
account's own day, which is the boundary the port promises.

**Removed objects are kept here**, unlike the campaign list: their spend
happened, and a ninety-day report must still carry it - with the name the
object had, which is why the name is read with the figures.

**Conversions are a result, not leads.** Google counts every conversion
action the account tracks - calls, site visits, form submissions - in one
fractional figure. It goes to ``results_reported``, rounded, and never into
the lead count: a lead here is a person with a name and a phone number,
and Google's lead form submissions arrive through their own route.

Money arrives in micros and leaves as the account currency's minor units.
CTR arrives as a fraction and leaves as a percentage, the shape every
other provider's ratio has in the metrics table.
"""

from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from typing import Any, Final

import httpx
from adskit.dto import MetricsDTO, PeopleCountDTO, SegmentMetricsDTO
from adskit.errors import InvalidRequest
from adskit.refs import BreakdownKind, ExternalRef, Level, MinorUnits, ProviderName

from googleadskit.campaigns import google_calls, micros_to_minor
from googleadskit.client import AdsClient

PROVIDER: Final = ProviderName("google")

_FIGURES: Final = (
    "segments.date, metrics.cost_micros, metrics.impressions, metrics.clicks, "
    "metrics.conversions, metrics.ctr, metrics.average_cpm, metrics.average_cpc, "
    "customer.currency_code"
)

# level: (GAQL resource, the fields that place a row, its JSON node)
_LEVELS: Final[dict[str, tuple[str, str]]] = {
    "campaign": ("campaign", "campaign.resource_name, campaign.name"),
    "adset": (
        "ad_group",
        "ad_group.resource_name, ad_group.name, campaign.resource_name",
    ),
    "ad": (
        "ad_group_ad",
        "ad_group_ad.resource_name, ad_group_ad.ad.name, ad_group_ad.ad.type, "
        "ad_group.resource_name, campaign.resource_name",
    ),
}

_PERCENT: Final = 100


class GoogleMetrics:
    """Daily figures per campaign, ad group or ad."""

    def __init__(self, *, http: httpx.Client | None = None) -> None:
        # Lent, never closed here: a test's mock transport, or a pool a
        # caller wants shared. ``None`` opens one per call.
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
        found = _LEVELS.get(level)
        if found is None:
            raise InvalidRequest(f"google has no daily figures at {level!r}")
        resource, placing = found
        query = (
            f"SELECT {placing}, {_FIGURES} FROM {resource} "
            f"WHERE segments.date BETWEEN '{since.isoformat()}' "
            f"AND '{until.isoformat()}'"
        )
        with google_calls(), AdsClient(token=token, http=self._http) as client:
            rows = list(client.search(account.id, query))
        return [_row(row, level=level) for row in rows]

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
        """No cuts yet: Google's segments are not mapped to the domain's.

        Empty rather than refused, and the reason is the caller. The nightly
        sync asks for Meta's cuts of every account and records a refusal as
        a night that did not finish - every night, for every Google account,
        over a gap that is known. Nothing reads a Google cut until Google's
        own screens are built, and those will say so when they do.
        """
        return []

    def fetch_people(
        self,
        *,
        account: ExternalRef,
        ranges: Sequence[tuple[date, date]],
        level: Level,
        token: str,
    ) -> list[PeopleCountDTO]:
        """No range counts yet, for the reason there are no cuts.

        Empty rather than refused: the sync asks every account, and the
        screens fall back to what the daily rows say where nothing is here.
        """
        return []


def _row(row: dict[str, Any], *, level: Level) -> MetricsDTO:
    figures = row.get("metrics", {})
    currency = str(row.get("customer", {}).get("currencyCode") or "")
    campaign = str(row.get("campaign", {}).get("resourceName") or "")
    group = str(row.get("adGroup", {}).get("resourceName") or "")
    ad_node = row.get("adGroupAd", {})
    ad = str(ad_node.get("resourceName") or "")

    if level == "campaign":
        own, name = campaign, str(row.get("campaign", {}).get("name") or "")
    elif level == "adset":
        own, name = group, str(row.get("adGroup", {}).get("name") or "")
    else:
        body = ad_node.get("ad", {})
        own, name = ad, str(body.get("name") or body.get("type") or "")

    return MetricsDTO(
        ref=ExternalRef(provider=PROVIDER, level=level, id=own),
        day=date.fromisoformat(str(row.get("segments", {}).get("date"))),
        campaign_external_id=campaign,
        adset_external_id=group,
        ad_external_id=ad,
        spend_minor=_money(figures.get("costMicros"), currency),
        currency=currency,
        impressions=_count(figures.get("impressions")),
        clicks=_count(figures.get("clicks")),
        results_reported=round(Decimal(str(figures.get("conversions") or 0))),
        ctr=Decimal(str(figures.get("ctr") or 0)) * _PERCENT,
        cpm_minor=_money(figures.get("averageCpm"), currency),
        cpc_minor=_money(figures.get("averageCpc"), currency),
        object_name=name,
    )


def _money(micros: object, currency: str) -> MinorUnits:
    return micros_to_minor(micros, currency) or MinorUnits(0)


def _count(value: object) -> int:
    """Google sends int64 counts as strings."""
    return int(str(value)) if value not in (None, "") else 0


__all__ = ["GoogleMetrics"]
