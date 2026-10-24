"""Google Ads campaigns, ad groups and ads as :class:`adskit.CampaignControlPort`."""

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from typing import Any, Final

import httpx
from adskit import PortNotAvailable
from adskit.dto import (
    ActionResult,
    AdDTO,
    AdPreviewDTO,
    AdSetDTO,
    CampaignDTO,
    ObjectsDTO,
    StatusDTO,
)
from adskit.errors import InvalidRequest
from adskit.refs import ExternalRef, Level, MinorUnits, ProviderName

from googleadskit.client import AdsClient
from googleadskit.errors import GoogleAdsError
from googleadskit.resources import customer_of, quoted
from googleadskit.rows import (
    BUDGET_CONSTRAINED,
    ad_dto,
    campaign_dto,
    delivery_of,
    group_dto,
    micros_to_minor,
    node_key,
)
from googleadskit.translate import translate_error
from googleadskit.writes import SETTABLE, change_budget, change_status, remove

PROVIDER: Final = ProviderName("google")

_CAMPAIGN_FIELDS: Final = (
    "campaign.resource_name, campaign.name, campaign.status, "
    "campaign.primary_status, campaign.advertising_channel_type, "
    "campaign.primary_status_reasons, campaign.start_date, "
    "campaign_budget.resource_name, campaign_budget.amount_micros, "
    "campaign_budget.explicitly_shared, customer.currency_code"
)
_GROUP_FIELDS: Final = (
    "ad_group.resource_name, ad_group.name, ad_group.status, "
    "ad_group.primary_status, ad_group.type, campaign.resource_name"
)
_AD_FIELDS: Final = (
    "ad_group_ad.resource_name, ad_group_ad.ad.name, ad_group_ad.ad.type, "
    "ad_group_ad.status, ad_group_ad.primary_status, ad_group.resource_name"
)

_FROM: Final[dict[str, tuple[str, str]]] = {
    "campaign": ("campaign", _CAMPAIGN_FIELDS),
    "adset": ("ad_group", _GROUP_FIELDS),
    "ad": ("ad_group_ad", _AD_FIELDS),
}


@contextmanager
def google_calls() -> Iterator[None]:
    """Google's failures as the domain's, for every call in this package."""
    try:
        yield
    except GoogleAdsError as exc:
        raise translate_error(exc) from exc


def _where_not_removed(resource: str) -> str:
    return f"WHERE {resource}.status != 'REMOVED'"


class GoogleCampaigns:
    """Read an account's campaigns, ad groups and ads; start and stop them."""

    def __init__(
        self, *, http: httpx.Client | None = None, rehearse_writes: bool = False
    ) -> None:
        self._http = http
        self._rehearse = rehearse_writes

    def list_campaigns(self, *, account: ExternalRef, token: str) -> list[CampaignDTO]:
        return [
            campaign_dto(row)
            for row in self._list(account=account, token=token, level="campaign")
        ]

    def list_adsets(self, *, account: ExternalRef, token: str) -> list[AdSetDTO]:
        return [
            group_dto(row)
            for row in self._list(account=account, token=token, level="adset")
        ]

    def list_ads(self, *, account: ExternalRef, token: str) -> list[AdDTO]:
        return [
            ad_dto(row) for row in self._list(account=account, token=token, level="ad")
        ]

    def read_objects(
        self, *, account: ExternalRef, refs: Sequence[ExternalRef], token: str
    ) -> ObjectsDTO:
        """These objects by resource name, one search per level asked for."""

        def named(level: Level) -> list[dict[str, Any]]:
            return self._named(account=account, refs=refs, token=token, level=level)

        return ObjectsDTO(
            campaigns=tuple(campaign_dto(row) for row in named("campaign")),
            adsets=tuple(group_dto(row) for row in named("adset")),
            ads=tuple(ad_dto(row) for row in named("ad")),
        )

    def get_status(self, *, ref: ExternalRef, token: str) -> StatusDTO:
        """One object's state, read fresh by its resource name."""
        resource, fields = self._source(ref.level)
        query = (
            f"SELECT {fields} FROM {resource} "
            f"WHERE {resource}.resource_name = '{quoted(ref.id)}'"
        )
        with google_calls(), AdsClient(token=token, http=self._http) as client:
            rows = list(client.search(customer_of(ref.id), query))
        if not rows:
            raise InvalidRequest(f"google has no {ref.level} {ref.id}")

        row = rows[0]
        node = row.get(node_key(resource), {})
        status = str(node.get("status") or "")
        primary = str(node.get("primaryStatus") or "")
        budget = None
        if ref.level == "campaign":
            budget = micros_to_minor(
                row.get("campaignBudget", {}).get("amountMicros"),
                str(row.get("customer", {}).get("currencyCode") or ""),
            )
        return StatusDTO(
            ref=ref,
            status=status,
            effective_status=primary,
            delivery=delivery_of(status=status, primary_status=primary),
            daily_budget_minor=budget,
        )

    def set_status(
        self, *, ref: ExternalRef, status: str, token: str, dry_run: bool = True
    ) -> ActionResult:
        """Pause or resume one object."""
        dry_run = dry_run or self._rehearse
        wanted = status.strip().lower()
        if wanted not in SETTABLE:
            raise InvalidRequest(f"{PROVIDER} cannot be asked for status {status!r}")
        with google_calls(), AdsClient(token=token, http=self._http) as client:
            answer = change_status(client, ref, status=wanted, validate_only=dry_run)
        return ActionResult(
            ok=True,
            ref=ref,
            applied={"status": wanted},
            dry_run=dry_run,
            raw_response=answer,
        )

    def set_budget(
        self,
        *,
        ref: ExternalRef,
        daily_budget_minor: MinorUnits,
        token: str,
        dry_run: bool = True,
    ) -> ActionResult:
        """The campaign's daily amount, changed on the budget it draws on."""
        dry_run = dry_run or self._rehearse
        with google_calls(), AdsClient(token=token, http=self._http) as client:
            answer = change_budget(
                client,
                ref,
                daily_budget_minor=daily_budget_minor,
                validate_only=dry_run,
            )
        return ActionResult(
            ok=True,
            ref=ref,
            applied={"daily_budget_minor": int(daily_budget_minor)},
            dry_run=dry_run,
            raw_response=answer,
        )

    def delete(
        self, *, ref: ExternalRef, token: str, dry_run: bool = True
    ) -> ActionResult:
        """Remove the object for good; Google keeps its history."""
        dry_run = dry_run or self._rehearse
        with google_calls(), AdsClient(token=token, http=self._http) as client:
            answer = remove(client, ref, validate_only=dry_run)
        return ActionResult(
            ok=True,
            ref=ref,
            applied={"removed": True},
            dry_run=dry_run,
            raw_response=answer,
        )

    def count_adsets(self, *, campaign: ExternalRef, token: str) -> int:
        raise PortNotAvailable(provider=PROVIDER, port="campaigns.count_adsets")

    def get_preview(
        self, *, ref: ExternalRef, ad_format: str, token: str
    ) -> AdPreviewDTO:
        raise PortNotAvailable(provider=PROVIDER, port="campaigns.get_preview")

    def set_end_time(
        self, *, ref: ExternalRef, end_time: str, token: str, dry_run: bool = True
    ) -> ActionResult:
        raise PortNotAvailable(provider=PROVIDER, port="campaigns.set_end_time")

    def set_spend_cap(
        self,
        *,
        ref: ExternalRef,
        spend_cap_minor: MinorUnits,
        token: str,
        dry_run: bool = True,
    ) -> ActionResult:
        raise PortNotAvailable(provider=PROVIDER, port="campaigns.set_spend_cap")

    @staticmethod
    def _source(level: Level) -> tuple[str, str]:
        found = _FROM.get(level)
        if found is None:
            raise InvalidRequest(f"google has no {level!r} objects to read")
        return found

    def _named(
        self,
        *,
        account: ExternalRef,
        refs: Sequence[ExternalRef],
        token: str,
        level: Level,
    ) -> list[dict[str, Any]]:
        names = ", ".join(f"'{quoted(ref.id)}'" for ref in refs if ref.level == level)
        if not names:
            return []
        resource, fields = self._source(level)
        where = f"WHERE {resource}.resource_name IN ({names})"
        query = f"SELECT {fields} FROM {resource} {where}"
        with google_calls(), AdsClient(token=token, http=self._http) as client:
            return list(client.search(account.id, query))

    def _list(
        self, *, account: ExternalRef, token: str, level: Level
    ) -> list[dict[str, Any]]:
        resource, fields = self._source(level)
        query = f"SELECT {fields} FROM {resource} {_where_not_removed(resource)}"
        with google_calls(), AdsClient(token=token, http=self._http) as client:
            return list(client.search(account.id, query))


__all__ = [
    "BUDGET_CONSTRAINED",
    "GoogleCampaigns",
    "delivery_of",
    "google_calls",
    "micros_to_minor",
]
