"""Google Ads campaigns, ad groups and ads as :class:`adskit.CampaignControlPort`.

Three GAQL reads and three writes - the switch, the budget, the removal,
built in :mod:`googleadskit.writes`. Google's hierarchy maps onto the
domain's one for one - campaign, ad group (our "adset"), ad - and the budget
sits on the campaign, the only level Google keeps one.

**Removed objects are not listed.** Google keeps them forever and they can
never run again; the mirror drops a row the provider stops sending, which
is what removed means. Their figures stay in the metrics table.

**Delivery** is read from ``primary_status``, Google's own summary of why
something is or is not serving, and the object's ``status`` beside it. A
group switched on under a paused campaign reports ``PAUSED`` as its
primary status while its own status is ``ENABLED`` - which is the
domain's ``paused_above``.

Ad ids are Google's ``adGroupAds`` names (``{group}~{ad}``): an ad is
addressed through the group it sits in, and that is the name a mutate
takes.
"""

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from typing import Any, Final

import httpx
from adskit import PortNotAvailable
from adskit.dto import (
    AccountStateDTO,
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
    # level: (GAQL resource, fields)
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
    """Read an account's campaigns, ad groups and ads; start and stop them.

    ``token`` is a live access token - the caller trades the stored refresh
    token for one through the connect port before it gets here.
    """

    def __init__(
        self, *, http: httpx.Client | None = None, rehearse_writes: bool = False
    ) -> None:
        # Lent, never closed here: a test's mock transport, or a pool a
        # caller wants shared. ``None`` opens one per call.
        self._http = http
        # True sends every write as ``validateOnly`` whatever ``dry_run``
        # says - the deployment's switch, set at registration.
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
        """Pause or resume one object.

        ``dry_run`` is Google's ``validateOnly``: the request is checked in
        full and nothing is changed. Setting a status twice is harmless, so
        a write whose answer was lost may simply be sent again.
        """
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
        """The campaign's daily amount, changed on the budget it draws on.

        A shared budget changes for every campaign on it - see
        :mod:`googleadskit.writes`. Setting the same figure twice is
        harmless, so a lost answer may be sent again.
        """
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

    # --- Not built yet ---------------------------------------------------
    # Each refuses by name, as ``Unavailable`` does for a whole port.

    def count_adsets(self, *, campaign: ExternalRef, token: str) -> int:
        raise PortNotAvailable(provider=PROVIDER, port="campaigns.count_adsets")

    def read_account(self, *, account: ExternalRef, token: str) -> AccountStateDTO:
        raise PortNotAvailable(provider=PROVIDER, port="campaigns.read_account")

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

    # --- Reading ---------------------------------------------------------

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
