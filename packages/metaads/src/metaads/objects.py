"""Reading named campaigns, ad sets and ads, rather than the whole account."""

from collections.abc import Sequence
from typing import Any, Final

from metaads.campaigns import (
    AD_FIELDS,
    AD_FIELDS_WITHOUT_CONTENT,
    ADSET_FIELDS,
    CAMPAIGN_FIELDS,
    UNREADABLE_CREATIVE_SUBCODE,
)
from metaads.client import GraphClient
from metaads.dto import AdRow, AdSetRow, CampaignRow
from metaads.errors import MetaAPIError
from metaads.parsing import parsed_all

_GONE_CODE: Final = 803
_MISSING_AT_PATH: Final = (100, 33)


def read_campaigns(
    *, ids: Sequence[str], token: str, client: GraphClient | None = None
) -> list[CampaignRow]:
    """These campaigns, as the account list would describe them."""
    rows = _read(ids=ids, fields=CAMPAIGN_FIELDS, token=token, client=client)
    return parsed_all(CampaignRow, rows)


def read_adsets(
    *, ids: Sequence[str], token: str, client: GraphClient | None = None
) -> list[AdSetRow]:
    """These ad sets, as the account list would describe them."""
    rows = _read(ids=ids, fields=ADSET_FIELDS, token=token, client=client)
    return parsed_all(AdSetRow, rows)


def read_ads(
    *, ids: Sequence[str], token: str, client: GraphClient | None = None
) -> list[AdRow]:
    """These ads, with their creative's content wherever Meta will give it."""
    rows = _read(
        ids=ids,
        fields=AD_FIELDS,
        token=token,
        client=client,
        fallback=AD_FIELDS_WITHOUT_CONTENT,
    )
    return parsed_all(AdRow, rows)


def _read(
    *,
    ids: Sequence[str],
    fields: str,
    token: str,
    client: GraphClient | None,
    fallback: str = "",
) -> list[dict[str, Any]]:
    """Every id at its own path, closing only a client opened here."""
    wanted = list(dict.fromkeys(item for item in ids if item))
    graph = client or GraphClient(token=token)
    try:
        return [
            row
            for object_id in wanted
            for row in _one(
                graph=graph, object_id=object_id, fields=fields, fallback=fallback
            )
        ]
    finally:
        if client is None:
            graph.close()


def _one(
    *, graph: GraphClient, object_id: str, fields: str, fallback: str
) -> list[dict[str, Any]]:
    """One object, without its content when that is what Meta refuses."""
    try:
        return [graph.get(object_id, fields=fields)]
    except MetaAPIError as exc:
        if exc.code == _GONE_CODE or (exc.code, exc.subcode) == _MISSING_AT_PATH:
            return []
        if fallback and exc.subcode == UNREADABLE_CREATIVE_SUBCODE:
            return [graph.get(object_id, fields=fallback)]
        raise


__all__ = [
    "AD_FIELDS_WITHOUT_CONTENT",
    "UNREADABLE_CREATIVE_SUBCODE",
    "read_ads",
    "read_adsets",
    "read_campaigns",
]
