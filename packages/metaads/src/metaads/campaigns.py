"""Reading the shape of an ad account: its campaigns, ad sets and ads."""

import logging
from typing import Any, Final

from metaads.client import GraphClient
from metaads.dto import AdRow, AdSetRow, CampaignRow
from metaads.errors import MetaAPIError
from metaads.parsing import parsed, parsed_all

logger = logging.getLogger(__name__)

CAMPAIGN_FIELDS = (
    "id,name,objective,status,effective_status,daily_budget,spend_cap,"
    "special_ad_categories,created_time,issues_info,recommendations"
)

REMOVED_STATUSES: Final = frozenset({"DELETED", "ARCHIVED"})

ADSET_FIELDS = (
    "id,name,campaign_id,status,effective_status,optimization_goal,"
    "billing_event,destination_type,daily_budget,targeting,promoted_object,"
    "learning_stage_info,start_time,end_time,issues_info,recommendations"
)

CREATIVE_SUBFIELDS = (
    "id,name,status,thumbnail_url,object_story_id,object_story_spec,"
    "effective_object_story_id,actor_id"
)
AD_FIELDS = (
    f"id,name,adset_id,status,effective_status,creative{{{CREATIVE_SUBFIELDS}}},"
    "issues_info,ad_review_feedback"
)

UNREADABLE_CREATIVE_SUBCODE: Final = 2446211

AD_FIELDS_WITHOUT_CONTENT: Final = (
    "id,name,adset_id,status,effective_status,creative{id},"
    "issues_info,ad_review_feedback"
)

PAGE_SIZE = 100

MIRROR_PAGES: Final = 100

BASE_STATUS_FIELDS = "status,effective_status"
BUDGET_STATUS_FIELDS = f"{BASE_STATUS_FIELDS},daily_budget"
ADSET_STATUS_FIELDS = f"{BUDGET_STATUS_FIELDS},learning_stage_info"

STATUS_FIELDS: dict[str, str] = {
    "campaign": BUDGET_STATUS_FIELDS,
    "adset": ADSET_STATUS_FIELDS,
    "ad": BASE_STATUS_FIELDS,
}


def list_campaigns(
    *, account_id: str, token: str, client: GraphClient | None = None
) -> list[CampaignRow]:
    """Every campaign in the account, as Meta currently describes it."""
    rows = _read(
        path=f"{account_id}/campaigns",
        fields=CAMPAIGN_FIELDS,
        token=token,
        client=client,
    )
    return parsed_all(CampaignRow, rows)


def list_adsets(
    *, account_id: str, token: str, client: GraphClient | None = None
) -> list[AdSetRow]:
    """Every ad set in the account, across every campaign."""
    rows = _read(
        path=f"{account_id}/adsets", fields=ADSET_FIELDS, token=token, client=client
    )
    return parsed_all(AdSetRow, rows)


def count_campaign_adsets(
    *, campaign_id: str, token: str, client: GraphClient | None = None
) -> int:
    """How many ad sets under one campaign are neither deleted nor archived."""
    rows = _read(
        path=f"{campaign_id}/adsets",
        fields="id,effective_status",
        token=token,
        client=client,
    )
    return sum(
        1
        for row in rows
        if str(row.get("effective_status") or "").upper() not in REMOVED_STATUSES
    )


def list_ads(
    *, account_id: str, token: str, client: GraphClient | None = None
) -> list[AdRow]:
    """Every ad in the account, across every ad set."""
    try:
        rows = _read(
            path=f"{account_id}/ads", fields=AD_FIELDS, token=token, client=client
        )
    except MetaAPIError as exc:
        if exc.subcode != UNREADABLE_CREATIVE_SUBCODE:
            raise
        logger.warning("ads of %s read without creative content: %s", account_id, exc)
        rows = _read(
            path=f"{account_id}/ads",
            fields=AD_FIELDS_WITHOUT_CONTENT,
            token=token,
            client=client,
        )
    return parsed_all(AdRow, rows)


def get_adset(
    *, adset_id: str, token: str, client: GraphClient | None = None
) -> AdSetRow:
    """One ad set, read fresh."""
    graph = client or GraphClient(token=token)
    try:
        row = graph.get(adset_id, fields=ADSET_STATUS_FIELDS)
    finally:
        if client is None:
            graph.close()

    return parsed(AdSetRow, row)


def get_object(
    *, object_id: str, fields: str, token: str, client: GraphClient | None = None
) -> dict[str, Any]:
    """One object's raw fields. The escape hatch for level-specific reads."""
    graph = client or GraphClient(token=token)
    try:
        return graph.get(object_id, fields=fields)
    finally:
        if client is None:
            graph.close()


def _read(
    *, path: str, fields: str, token: str, client: GraphClient | None
) -> list[dict[str, Any]]:
    """One paged list read, closing only a client this function opened."""
    graph = client or GraphClient(token=token)
    try:
        return graph.get_all(
            path, fields=fields, limit=PAGE_SIZE, max_pages=MIRROR_PAGES
        )
    finally:
        if client is None:
            graph.close()
