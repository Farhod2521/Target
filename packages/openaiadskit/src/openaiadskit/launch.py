"""Making one ChatGPT campaign: a campaign, one ad group, one chat card.

Not a port - OpenAI's own sequence, the way ``googleadskit.launch`` is
Google's. Four calls, in order: the image (when one is given), the
campaign, its ad group, its ad.

**Atomic by hand.** OpenAI has no transaction across objects, so the
campaign is created paused and switched on only after its ad exists. If a
step after the campaign fails, the campaign is archived before the failure
is raised: nothing half-made can start spending. The archive is best
effort; a failure there is logged by the caller from the original error.

**Idempotent.** Every create carries ``{key}:{step}`` as its
``Idempotency-Key``, so a caller that repeats a lost answer with the same
key gets the same objects back instead of a second campaign.

The limits are OpenAI's and are checked before the first call, so a
refusal names the field rather than costing a round trip:
title 3-50 characters, body up to 100, an http(s) landing page, a daily
budget of at least one unit of the account currency.
"""

import re
from dataclasses import dataclass
from typing import Any, Final, Literal

from adskit.errors import InvalidRequest

from openaiadskit.client import AdsClient
from openaiadskit.errors import OpenAIAdsError

TITLE_MIN: Final = 3
TITLE_MAX: Final = 50
BODY_MAX: Final = 100
NAME_MIN: Final = 3
NAME_MAX: Final = 1000
URL_MAX: Final = 2048
MICROS_MIN: Final = 1_000_000
HINTS_MAX: Final = 20
HINT_MAX: Final = 300
_COUNTRY: Final = re.compile(r"^[A-Z]{2}$")

Bidding = Literal["clicks", "impressions"]


@dataclass(frozen=True, slots=True)
class ImageSpec:
    """The card's picture: an uploaded ``file_id``, the file, or its address."""

    content: bytes = b""
    filename: str = "image.png"
    content_type: str = "image/png"
    url: str = ""
    file_id: str = ""


@dataclass(frozen=True, slots=True)
class ChatCardSpec:
    """Everything one campaign with one chat card needs.

    ``countries`` are ISO codes; ``place_ids`` are ``geo_lookup`` ids for
    markets and regions inside them. At least one of the two.
    ``max_bid_micros`` zero lets OpenAI bid (``maximize_clicks``).
    """

    name: str
    daily_budget_micros: int
    title: str
    body: str
    target_url: str
    countries: tuple[str, ...] = ()
    place_ids: tuple[str, ...] = ()
    context_hints: tuple[str, ...] = ()
    bidding: Bidding = "clicks"
    max_bid_micros: int = 0
    image: ImageSpec | None = None
    start_active: bool = True
    query_string_template: str = ""
    platforms: tuple[str, ...] = ()

    def checked(self) -> "ChatCardSpec":
        """This spec, or the first rule it breaks as ``InvalidRequest``."""
        if not NAME_MIN <= len(self.name.strip()) <= NAME_MAX:
            raise InvalidRequest("campaign name", code="name")
        if self.daily_budget_micros < MICROS_MIN:
            raise InvalidRequest("daily budget below one unit", code="budget")
        if not TITLE_MIN <= len(self.title.strip()) <= TITLE_MAX:
            raise InvalidRequest("title length", code="title")
        if not self.body.strip() or len(self.body.strip()) > BODY_MAX:
            raise InvalidRequest("body length", code="body")
        url = self.target_url.strip()
        if not url.startswith(("https://", "http://")) or len(url) > URL_MAX:
            raise InvalidRequest("landing page", code="target_url")
        if not self.countries and not self.place_ids:
            raise InvalidRequest("no location", code="locations")
        if any(not _COUNTRY.match(code) for code in self.countries):
            raise InvalidRequest("country code", code="countries")
        if len(self.context_hints) > HINTS_MAX or any(
            not hint.strip() or len(hint) > HINT_MAX for hint in self.context_hints
        ):
            raise InvalidRequest("context hints", code="context_hints")
        if self.max_bid_micros < 0:
            raise InvalidRequest("max bid", code="max_bid")
        return self


@dataclass(frozen=True, slots=True)
class CreatedChatCampaign:
    campaign_id: str
    ad_group_id: str
    ad_id: str
    file_id: str
    active: bool
    review_status: str


def upload_image(client: AdsClient, image: ImageSpec) -> str:
    """The image's ``file_id``; one already uploaded is used as it is."""
    if image.file_id:
        return image.file_id
    if image.url:
        answer = client.post("upload", {"image_url": image.url})
    else:
        answer = client.upload(
            content=image.content,
            filename=image.filename,
            content_type=image.content_type,
        )
    file_id = str(answer.get("file_id") or "")
    if not file_id:
        raise InvalidRequest("upload answered without a file id", code="upload")
    return file_id


def campaign_body(spec: ChatCardSpec) -> dict[str, Any]:
    locations: dict[str, Any] = {}
    if spec.countries:
        locations["countries"] = list(spec.countries)
    if spec.place_ids:
        locations["include"] = [{"id": place} for place in spec.place_ids]
    targeting: dict[str, Any] = {"locations": locations}
    if spec.platforms:
        targeting["platforms"] = {"included": list(spec.platforms)}
    body: dict[str, Any] = {
        "name": spec.name.strip(),
        "status": "paused",
        "bidding_type": spec.bidding,
        "budget": {"daily_spend_limit_micros": spec.daily_budget_micros},
        "targeting": targeting,
    }
    if spec.query_string_template:
        body["landing_page_configuration"] = {
            "query_string_template": spec.query_string_template
        }
    return body


def group_body(spec: ChatCardSpec, *, campaign_id: str) -> dict[str, Any]:
    event = "click" if spec.bidding == "clicks" else "impression"
    bidding: dict[str, Any] = {"billing_event_type": event}
    if spec.max_bid_micros:
        bidding |= {"strategy": "fixed_bid", "max_bid_micros": spec.max_bid_micros}
    elif spec.bidding == "clicks":
        bidding["strategy"] = "maximize_clicks"
    return {
        "campaign_id": campaign_id,
        "name": spec.name.strip()[:NAME_MAX],
        "status": "active",
        "context_hints": [hint.strip() for hint in spec.context_hints],
        "bidding_config": bidding,
    }


def ad_body(spec: ChatCardSpec, *, ad_group_id: str, file_id: str) -> dict[str, Any]:
    creative: dict[str, Any] = {
        "type": "chat_card",
        "title": spec.title.strip(),
        "body": spec.body.strip(),
        "target_url": spec.target_url.strip(),
    }
    if file_id:
        creative["file_id"] = file_id
    return {
        "ad_group_id": ad_group_id,
        "name": spec.name.strip()[:NAME_MAX],
        "status": "active",
        "creative": creative,
    }


def create_chat_campaign(
    client: AdsClient, spec: ChatCardSpec, *, key: str
) -> CreatedChatCampaign:
    """The whole campaign, or nothing that can spend. See the module doc."""
    spec.checked()
    file_id = upload_image(client, spec.image) if spec.image else ""
    campaign = client.post(
        "campaigns", campaign_body(spec), idempotency_key=f"{key}:campaign"
    )
    campaign_id = str(campaign["id"])
    try:
        group = client.post(
            "ad_groups",
            group_body(spec, campaign_id=campaign_id),
            idempotency_key=f"{key}:ad_group",
        )
        ad = client.post(
            "ads",
            ad_body(spec, ad_group_id=str(group["id"]), file_id=file_id),
            idempotency_key=f"{key}:ad",
        )
        if spec.start_active:
            client.post(f"campaigns/{campaign_id}/activate")
    except (OpenAIAdsError, KeyError):
        _archive_quietly(client, campaign_id)
        raise
    return CreatedChatCampaign(
        campaign_id=campaign_id,
        ad_group_id=str(group["id"]),
        ad_id=str(ad["id"]),
        file_id=file_id,
        active=spec.start_active,
        review_status=str(ad.get("review_status") or ""),
    )


def _archive_quietly(client: AdsClient, campaign_id: str) -> None:
    try:
        client.post(f"campaigns/{campaign_id}/archive")
    except OpenAIAdsError:
        pass


__all__ = [
    "BODY_MAX",
    "TITLE_MAX",
    "TITLE_MIN",
    "ChatCardSpec",
    "CreatedChatCampaign",
    "ImageSpec",
    "ad_body",
    "campaign_body",
    "create_chat_campaign",
    "group_body",
    "upload_image",
]
