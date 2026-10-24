"""Daily Google Ads figures as :class:`adskit.MetricsPort`."""

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
        """No cuts yet: Google's segments are not mapped to the domain's."""
        return []

    def fetch_people(
        self,
        *,
        account: ExternalRef,
        ranges: Sequence[tuple[date, date]],
        level: Level,
        token: str,
    ) -> list[PeopleCountDTO]:
        """No range counts yet, for the reason there are no cuts."""
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
