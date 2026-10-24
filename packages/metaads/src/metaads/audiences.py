"""Custom audiences: the lists an advertiser owns, held on Meta."""

from typing import Final

from adskit.dto import AudienceRuleDTO, LookalikeSpecDTO

from metaads.audience_rules import rule_document
from metaads.client import GraphClient
from metaads.dto import CustomAudienceRow
from metaads.lookalikes import SUBTYPE_LOOKALIKE, lookalike_spec
from metaads.parsing import parsed, parsed_all
from metaads.writing import fake_id, graph_client, id_of, is_dry_run_id, post_object

_AUDIENCE: Final = "audience"
_RULE_AUDIENCE: Final = "rule_audience"
_LOOKALIKE: Final = "lookalike"

AUDIENCE_FIELDS: Final = (
    "id,name,description,subtype,customer_file_source,"
    "approximate_count_lower_bound,approximate_count_upper_bound,"
    "operation_status,delivery_status,data_source,rule,retention_days,"
    "lookalike_spec,time_created,time_updated"
)

PAGE_SIZE: Final = 100

SUBTYPE_CUSTOM: Final = "CUSTOM"

CUSTOMER_FILE_SOURCE: Final = "USER_PROVIDED_ONLY"

TERMS_URL: Final = "https://business.facebook.com/ads/manage/customaudiences/tos/"


def terms_url(account_id: str = "") -> str:
    """The terms page, for one account when we know which."""
    if not account_id:
        return TERMS_URL
    return f"{TERMS_URL}?act={account_id.removeprefix('act_')}"


def list_audiences(
    *, account_id: str, token: str, client: GraphClient | None = None
) -> list[CustomAudienceRow]:
    """Every custom audience on the account, whatever state each is in."""
    with graph_client(client, token) as graph:
        rows = graph.get_all(
            f"{account_id}/customaudiences", fields=AUDIENCE_FIELDS, limit=PAGE_SIZE
        )
    return parsed_all(CustomAudienceRow, rows)


def get_audience(
    *, audience_id: str, token: str, client: GraphClient | None = None
) -> CustomAudienceRow:
    """One audience, read on its own."""
    with graph_client(client, token) as graph:
        payload = graph.get(audience_id, fields=AUDIENCE_FIELDS)
    return parsed(CustomAudienceRow, payload)


def create_audience(
    *,
    account_id: str,
    name: str,
    description: str = "",
    token: str,
    client: GraphClient | None = None,
    dry_run: bool = True,
) -> str:
    """Create an empty audience a customer list can be uploaded into."""
    if dry_run:
        return fake_id(_AUDIENCE)

    payload = post_object(
        path=f"{account_id}/customaudiences",
        data={
            "name": name,
            "description": description,
            "subtype": SUBTYPE_CUSTOM,
            "customer_file_source": CUSTOMER_FILE_SOURCE,
        },
        token=token,
        client=client,
    )
    return id_of(payload)


def create_rule_audience(
    *,
    account_id: str,
    name: str,
    description: str = "",
    rule: AudienceRuleDTO,
    token: str,
    client: GraphClient | None = None,
    dry_run: bool = True,
) -> str:
    """Create an audience Meta populates itself, from a rule."""
    if dry_run:
        return fake_id(_RULE_AUDIENCE)

    payload = post_object(
        path=f"{account_id}/customaudiences",
        data={
            "name": name,
            "description": description,
            "rule": rule_document(rule),
        },
        token=token,
        client=client,
    )
    return id_of(payload)


def create_lookalike_audience(
    *,
    account_id: str,
    name: str,
    description: str = "",
    spec: LookalikeSpecDTO,
    token: str,
    client: GraphClient | None = None,
    dry_run: bool = True,
) -> str:
    """Create an audience of people who resemble an audience that exists."""
    if dry_run:
        return fake_id(_LOOKALIKE)

    payload = post_object(
        path=f"{account_id}/customaudiences",
        data={
            "name": name,
            "description": description,
            "subtype": SUBTYPE_LOOKALIKE,
            "origin_audience_id": spec.origin.id,
            "lookalike_spec": lookalike_spec(spec),
        },
        token=token,
        client=client,
    )
    return id_of(payload)


def delete_audience(
    *,
    audience_id: str,
    token: str,
    client: GraphClient | None = None,
    dry_run: bool = True,
) -> bool:
    """Remove the audience and everything uploaded into it."""
    if dry_run or is_dry_run_id(audience_id):
        return True

    with graph_client(client, token) as graph:
        payload = graph.delete(audience_id)
    return bool(payload.get("success", True))


__all__ = [
    "AUDIENCE_FIELDS",
    "CUSTOMER_FILE_SOURCE",
    "SUBTYPE_CUSTOM",
    "TERMS_URL",
    "create_audience",
    "create_lookalike_audience",
    "create_rule_audience",
    "delete_audience",
    "get_audience",
    "list_audiences",
    "terms_url",
]
