"""What a token can reach: which ad accounts, and which pages."""

import logging
from collections.abc import Iterable, Sequence
from typing import Any, Final
from urllib.parse import urlencode

from metaads.client import GraphClient
from metaads.dto import AdAccountDTO, PageDTO, PixelDTO, PixelEventRow
from metaads.errors import MetaAPIError, MetaError
from metaads.parsing import parsed_all

logger = logging.getLogger(__name__)

AD_ACCOUNT_FIELDS = (
    "id,name,currency,timezone_name,account_status,spend_cap,amount_spent,"
    "min_daily_budget,disable_reason,tos_accepted,user_tos_accepted,business{id}"
)

BUSINESS_FIELDS: Final = "id,name"

BUSINESS_AD_ACCOUNT_EDGES: Final[tuple[str, ...]] = (
    "owned_ad_accounts",
    "client_ad_accounts",
)

MAX_BUSINESSES: Final = 25

BLOCKED_ACCOUNT_STATUSES: Final[frozenset[int]] = frozenset({2, 3, 100, 101})

UNSETTLED_STATUS: Final = 3

BASE_PAGE_FIELDS = (
    "id,name,access_token,tasks,leadgen_tos_accepted,location,"
    "instagram_business_account{id,username}"
)
PAGE_FIELDS = BASE_PAGE_FIELDS + ",connected_instagram_account{id,username}"

_FIELD_REFUSALS: Final[frozenset[int]] = frozenset({10, 100, 200})

ADVERTISING_TASKS: Final[frozenset[str]] = frozenset({"ADVERTISE", "MANAGE"})

PIXEL_FIELDS = "id,name,last_fired_time,is_unavailable"


def owes_payment(account_status: int) -> bool:
    """Whether this account is stopped over a bill it has not paid."""
    return account_status == UNSETTLED_STATUS


def may_run_ads(account_status: int) -> bool:
    """Whether this ad account can carry a campaign at all."""
    return account_status not in BLOCKED_ACCOUNT_STATUSES


def may_advertise(tasks: Sequence[str]) -> bool:
    """Whether this role can create ads and lead forms on the page."""
    return any(task in ADVERTISING_TASKS for task in tasks)


def list_ad_accounts(
    *, token: str, client: GraphClient | None = None
) -> list[AdAccountDTO]:
    """Every ad account this token can act on, from all three places."""
    graph = client or GraphClient(token=token)
    try:
        rows = graph.get_all("me/adaccounts", fields=AD_ACCOUNT_FIELDS, limit=100)
        rows.extend(_business_ad_account_rows(graph))
    finally:
        if client is None:
            graph.close()

    return parsed_all(AdAccountDTO, _unique_by_id(rows))


def _business_ad_account_rows(graph: GraphClient) -> list[dict[str, Any]]:
    """The ad account rows reachable through this person's businesses."""
    try:
        payload = graph.get(
            "me/businesses", fields=BUSINESS_FIELDS, limit=MAX_BUSINESSES
        )
    except MetaError as exc:
        logger.warning("businesses could not be listed: %s", exc)
        return []

    businesses = payload.get("data", [])
    if payload.get("paging", {}).get("next"):
        logger.warning(
            "more than %d businesses; the rest were not swept", MAX_BUSINESSES
        )

    rows: list[dict[str, Any]] = []
    for business in businesses:
        business_id = str(business.get("id") or "")
        if not business_id:
            continue
        for edge in BUSINESS_AD_ACCOUNT_EDGES:
            try:
                rows.extend(
                    _owned_by(
                        graph.get_all(
                            f"{business_id}/{edge}",
                            fields=AD_ACCOUNT_FIELDS,
                            limit=100,
                        ),
                        business_id=business_id,
                    )
                )
            except MetaError as exc:
                logger.warning("%s/%s could not be listed: %s", business_id, edge, exc)
    return rows


def _owned_by(rows: list[dict[str, Any]], *, business_id: str) -> list[dict[str, Any]]:
    """Name the business these rows were reached through, where they do not."""
    for row in rows:
        if not row.get("business"):
            row["business"] = {"id": business_id}
    return rows


def _unique_by_id(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """One row per account id, in the order they were first seen."""
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for row in rows:
        account_id = str(row.get("id") or "")
        if account_id and account_id in seen:
            continue
        if account_id:
            seen.add(account_id)
        unique.append(row)
    return unique


def list_pixels(
    *, account_id: str, token: str, client: GraphClient | None = None
) -> list[PixelDTO]:
    """Every conversion pixel on one ad account."""
    graph = client or GraphClient(token=token)
    try:
        rows = graph.get_all(f"{account_id}/adspixels", fields=PIXEL_FIELDS, limit=100)
    finally:
        if client is None:
            graph.close()

    return parsed_all(PixelDTO, rows)


PIXEL_STATS_DAYS: Final = 7

EVENT_AGGREGATION: Final = "event"


def pixel_events(
    *, pixel_id: str, token: str, client: GraphClient | None = None
) -> list[PixelEventRow]:
    """Which events this pixel has reported in the provider's own window."""
    graph = client or GraphClient(token=token)
    try:
        rows = graph.get_all(
            f"{pixel_id}/stats",
            aggregation=EVENT_AGGREGATION,
        )
    finally:
        if client is None:
            graph.close()

    counted: dict[str, int] = {}
    for row in rows:
        for entry in row.get("data") or ():
            if not isinstance(entry, dict):
                continue
            name = str(entry.get("value") or "").strip()
            if not name:
                continue
            counted[name] = counted.get(name, 0) + _times(entry.get("count"))

    return [
        PixelEventRow(event=name, count=times)
        for name, times in sorted(counted.items(), key=lambda pair: -pair[1])
    ]


def _times(value: object) -> int:
    """How many, as an integer. Meta answers in strings here and in numbers
    elsewhere on the same object, so neither is assumed.
    """
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return 0


def list_pages(*, token: str, client: GraphClient | None = None) -> list[PageDTO]:
    """Every page this token can see, each with its own token."""
    graph = client or GraphClient(token=token)
    try:
        try:
            rows = graph.get_all("me/accounts", fields=PAGE_FIELDS, limit=100)
        except MetaAPIError as exc:
            if exc.code not in _FIELD_REFUSALS:
                raise
            logger.warning("page list refused the full field set: %s", exc)
            rows = graph.get_all("me/accounts", fields=BASE_PAGE_FIELDS, limit=100)
    finally:
        if client is None:
            graph.close()

    return parsed_all(PageDTO, rows)


ADS_MANAGER_URL: Final = "https://adsmanager.facebook.com/adsmanager/manage/campaigns"


def manager_url(account_id: str = "") -> str:
    """Ads Manager, opened on one account when we know which."""
    if not account_id:
        return ADS_MANAGER_URL
    return f"{ADS_MANAGER_URL}?{urlencode({'act': account_id.removeprefix('act_')})}"


BILLING_URL: Final = (
    "https://business.facebook.com/latest/billing_hub/payment_settings/"
)


def billing_url(account_id: str = "") -> str:
    """The billing page, for one ad account when we know which."""
    if not account_id:
        return BILLING_URL
    return f"{BILLING_URL}?{urlencode({'asset_id': account_id.removeprefix('act_')})}"


ACCOUNT_QUALITY_URL: Final = "https://www.facebook.com/accountquality"
IDENTITY_URL: Final = "https://www.facebook.com/id"


ASSET_LIBRARY_URL: Final = "https://business.facebook.com/asset_library/ad_accounts"


def media_library_url(account_id: str = "", business_id: str = "") -> str:
    """Where an advertiser puts a picture that an ad here can then use."""
    if not business_id or not account_id:
        return manager_url(account_id)

    return f"{ASSET_LIBRARY_URL}?" + urlencode(
        {
            "business_id": business_id,
            "global_scope_id": business_id,
            "ad_account": account_id.removeprefix("act_"),
        }
    )
