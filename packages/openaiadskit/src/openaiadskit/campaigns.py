"""ChatGPT Ads campaigns, ad groups and ads as :class:`adskit.CampaignControlPort`.

OpenAI's hierarchy maps onto the domain's one for one - campaign, ad group
(our "adset"), ad. Budgets sit on the campaign, daily and lifetime, in
micros.

**Children are read through their parent.** An ad group's answer does not
name its campaign, nor an ad its group, so the lists walk down: campaigns,
then each campaign's groups, then each group's ads. That costs a call per
parent, which the account's 600-a-minute budget absorbs for any account a
small business runs.

**Archived objects are not listed**, as Google's removed ones are not:
they can never run again.

**No dry run at OpenAI.** Only the bulk endpoint can validate without
writing, so a rehearsed write here sends nothing and says so in its result.
"""

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import datetime
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
from adskit.refs import ExternalRef, Level, MinorUnits

from openaiadskit.accounts import read_ad_account
from openaiadskit.client import AdsClient
from openaiadskit.errors import OpenAIAdsError
from openaiadskit.rows import (
    ARCHIVED,
    PROVIDER,
    ad_dto,
    campaign_dto,
    delivery_of,
    group_dto,
    issue_codes,
    micros_to_minor,
    minor_to_micros,
)
from openaiadskit.translate import translate_error

# Our level name and OpenAI's collection for it.
COLLECTIONS: Final[dict[str, str]] = {
    "campaign": "campaigns",
    "adset": "ad_groups",
    "ad": "ads",
}
SETTABLE: Final[dict[str, str]] = {"active": "activate", "paused": "pause"}
_ISSUES: Final[dict[str, str | list[str]]] = {"include": ["serving_issues"]}


def issues_of(**filters: str) -> dict[str, str | list[str]]:
    """A list query that also asks why each object is not serving."""
    return {**filters, **_ISSUES}


@contextmanager
def openai_calls() -> Iterator[None]:
    """OpenAI's failures as the domain's, for every call in this package."""
    try:
        yield
    except OpenAIAdsError as exc:
        raise translate_error(exc) from exc


def collection(level: Level) -> str:
    found = COLLECTIONS.get(level)
    if found is None:
        raise InvalidRequest(f"{PROVIDER} has no {level!r} objects")
    return found


def live(rows: Iterator[dict[str, Any]]) -> list[dict[str, Any]]:
    return [row for row in rows if row.get("status") != ARCHIVED and row.get("id")]


# --- Reads on an open client ---------------------------------------------
# For a caller that already holds the client and the account currency and
# would otherwise pay for a second ``GET /ad_account`` per question.


def campaigns_of(client: AdsClient, *, currency: str) -> list[CampaignDTO]:
    return [
        campaign_dto(row, currency=currency)
        for row in live(client.pages("campaigns", _ISSUES))
    ]


def groups_of(client: AdsClient, *, campaign_id: str, currency: str) -> list[AdSetDTO]:
    return [
        group_dto(row, campaign_id=campaign_id, currency=currency)
        for row in live(client.pages("ad_groups", issues_of(campaign_id=campaign_id)))
    ]


def ads_of(client: AdsClient, *, ad_group_id: str) -> list[AdDTO]:
    return [
        ad_dto(row, ad_group_id=ad_group_id)
        for row in live(client.pages("ads", issues_of(ad_group_id=ad_group_id)))
    ]


class OpenAICampaigns:
    """Read an account's campaigns, ad groups and ads; start and stop them.

    ``token`` is the advertiser's API key, as stored.
    """

    def __init__(
        self, *, http: httpx.Client | None = None, rehearse_writes: bool = False
    ) -> None:
        self._http = http
        # True rehearses every write whatever ``dry_run`` says - the
        # deployment's switch, set at registration.
        self._rehearse = rehearse_writes

    def _client(self, token: str) -> AdsClient:
        return AdsClient(api_key=token, http=self._http)

    def list_campaigns(self, *, account: ExternalRef, token: str) -> list[CampaignDTO]:
        with openai_calls(), self._client(token) as client:
            return campaigns_of(client, currency=read_ad_account(client).currency)

    def list_adsets(self, *, account: ExternalRef, token: str) -> list[AdSetDTO]:
        with openai_calls(), self._client(token) as client:
            currency = read_ad_account(client).currency
            return [
                group_dto(row, campaign_id=campaign_id, currency=currency)
                for campaign_id, row in _groups(client)
            ]

    def list_ads(self, *, account: ExternalRef, token: str) -> list[AdDTO]:
        with openai_calls(), self._client(token) as client:
            return [
                ad_dto(ad, ad_group_id=str(group["id"]))
                for _, group in _groups(client)
                for ad in live(
                    client.pages("ads", issues_of(ad_group_id=str(group["id"])))
                )
            ]

    def get_status(self, *, ref: ExternalRef, token: str) -> StatusDTO:
        """One object's state, read fresh."""
        with openai_calls(), self._client(token) as client:
            item = client.get(f"{collection(ref.level)}/{ref.id}", _ISSUES)
            budget = None
            if ref.level == "campaign":
                currency = read_ad_account(client).currency
                budget = micros_to_minor(
                    (item.get("budget") or {}).get("daily_spend_limit_micros"), currency
                )
        status = str(item.get("status") or "")
        codes = issue_codes(item)
        return StatusDTO(
            ref=ref,
            status=status,
            effective_status=codes[0] if codes else status,
            delivery=delivery_of(status=status, issues=codes, level=ref.level),
            daily_budget_minor=budget,
        )

    def count_adsets(self, *, campaign: ExternalRef, token: str) -> int:
        with openai_calls(), self._client(token) as client:
            return len(live(client.pages("ad_groups", {"campaign_id": campaign.id})))

    def set_status(
        self, *, ref: ExternalRef, status: str, token: str, dry_run: bool = True
    ) -> ActionResult:
        """Pause or resume one object. Setting a status twice is harmless."""
        dry_run = dry_run or self._rehearse
        wanted = status.strip().lower()
        verb = SETTABLE.get(wanted)
        if verb is None:
            raise InvalidRequest(f"{PROVIDER} cannot be asked for status {status!r}")
        path = f"{collection(ref.level)}/{ref.id}/{verb}"
        return self._write(
            ref, path, None, applied={"status": wanted}, dry_run=dry_run, token=token
        )

    def set_budget(
        self,
        *,
        ref: ExternalRef,
        daily_budget_minor: MinorUnits,
        token: str,
        dry_run: bool = True,
    ) -> ActionResult:
        """The campaign's daily amount. OpenAI keeps budgets on campaigns only."""
        dry_run = dry_run or self._rehearse
        self._campaign_only(ref, "budget")
        with openai_calls(), self._client(token) as client:
            currency = read_ad_account(client).currency
            budget = self._budget(client, ref)
            budget["daily_spend_limit_micros"] = minor_to_micros(
                daily_budget_minor, currency
            )
            return self._send(
                client,
                ref,
                f"campaigns/{ref.id}",
                {"budget": budget},
                applied={"daily_budget_minor": int(daily_budget_minor)},
                dry_run=dry_run,
            )

    def set_spend_cap(
        self,
        *,
        ref: ExternalRef,
        spend_cap_minor: MinorUnits,
        token: str,
        dry_run: bool = True,
    ) -> ActionResult:
        """The campaign's lifetime limit, beside its daily one."""
        dry_run = dry_run or self._rehearse
        self._campaign_only(ref, "spend cap")
        with openai_calls(), self._client(token) as client:
            currency = read_ad_account(client).currency
            budget = self._budget(client, ref)
            budget["lifetime_spend_limit_micros"] = minor_to_micros(
                spend_cap_minor, currency
            )
            return self._send(
                client,
                ref,
                f"campaigns/{ref.id}",
                {"budget": budget},
                applied={"spend_cap_minor": int(spend_cap_minor)},
                dry_run=dry_run,
            )

    def set_end_time(
        self, *, ref: ExternalRef, end_time: str, token: str, dry_run: bool = True
    ) -> ActionResult:
        """When the campaign stops. ``end_time`` is ISO-8601 with an offset."""
        dry_run = dry_run or self._rehearse
        self._campaign_only(ref, "end time")
        try:
            moment = datetime.fromisoformat(end_time)
        except ValueError as exc:
            raise InvalidRequest(f"not an ISO-8601 time: {end_time!r}") from exc
        if moment.tzinfo is None:
            raise InvalidRequest("an end time needs its offset")
        seconds = int(moment.timestamp())
        return self._write(
            ref,
            f"campaigns/{ref.id}",
            {"end_time": seconds},
            applied={"end_time": end_time},
            dry_run=dry_run,
            token=token,
        )

    def delete(
        self, *, ref: ExternalRef, token: str, dry_run: bool = True
    ) -> ActionResult:
        """Archive the object: it stops for good, its history stays."""
        dry_run = dry_run or self._rehearse
        path = f"{collection(ref.level)}/{ref.id}/archive"
        return self._write(
            ref, path, None, applied={"removed": True}, dry_run=dry_run, token=token
        )

    # --- Not built yet ---------------------------------------------------

    def read_objects(
        self, *, account: ExternalRef, refs: Sequence[ExternalRef], token: str
    ) -> ObjectsDTO:
        raise PortNotAvailable(provider=PROVIDER, port="campaigns.read_objects")

    def read_account(self, *, account: ExternalRef, token: str) -> AccountStateDTO:
        raise PortNotAvailable(provider=PROVIDER, port="campaigns.read_account")

    def get_preview(
        self, *, ref: ExternalRef, ad_format: str, token: str
    ) -> AdPreviewDTO:
        raise PortNotAvailable(provider=PROVIDER, port="campaigns.get_preview")

    # --- Writing ---------------------------------------------------------

    @staticmethod
    def _campaign_only(ref: ExternalRef, what: str) -> None:
        if ref.level != "campaign":
            raise InvalidRequest(f"{PROVIDER} keeps a {what} on campaigns only")

    @staticmethod
    def _budget(client: AdsClient, ref: ExternalRef) -> dict[str, Any]:
        """The campaign's budget as it stands: an update replaces it whole."""
        found = client.get(f"campaigns/{ref.id}").get("budget") or {}
        return {key: value for key, value in found.items() if value is not None}

    def _write(
        self,
        ref: ExternalRef,
        path: str,
        body: dict[str, Any] | None,
        *,
        applied: dict[str, Any],
        dry_run: bool,
        token: str,
    ) -> ActionResult:
        if dry_run:
            return ActionResult(ok=True, ref=ref, applied=applied, dry_run=True)
        with openai_calls(), self._client(token) as client:
            return self._send(client, ref, path, body, applied=applied, dry_run=False)

    @staticmethod
    def _send(
        client: AdsClient,
        ref: ExternalRef,
        path: str,
        body: dict[str, Any] | None,
        *,
        applied: dict[str, Any],
        dry_run: bool,
    ) -> ActionResult:
        if dry_run:
            return ActionResult(ok=True, ref=ref, applied=applied, dry_run=True)
        answer = client.post(path, body)
        return ActionResult(
            ok=True, ref=ref, applied=applied, dry_run=False, raw_response=answer
        )


def _groups(client: AdsClient) -> Iterator[tuple[str, dict[str, Any]]]:
    """Every live ad group, beside the id of the campaign it sits in."""
    for campaign in live(client.pages("campaigns")):
        campaign_id = str(campaign["id"])
        for group in live(
            client.pages("ad_groups", issues_of(campaign_id=campaign_id))
        ):
            yield campaign_id, group


__all__ = [
    "COLLECTIONS",
    "OpenAICampaigns",
    "ads_of",
    "campaigns_of",
    "collection",
    "groups_of",
    "openai_calls",
]
