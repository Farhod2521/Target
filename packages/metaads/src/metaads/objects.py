"""Reading named campaigns, ad sets and ads, rather than the whole account.

Apart from :mod:`metaads.campaigns` because the two answer different
questions. The account lists say what an account holds, and a row missing
from them means the object is gone; this says what a handful of known ids
look like now, and says nothing about anything else.

**Why it exists.** The ``/act_<id>/ads`` read is all or nothing: one advert
Meta will not describe fails the whole list. An Advantage+ creative whose
asset feed disagrees with its story spec does exactly that (``100/2446211``),
and it can be an advert nobody in this product ever touched. A read by id
reaches only the objects asked for, so a stranger's broken advert cannot
stand between a launch and its own three objects.

**One request per id.** Graph v26.0 refuses the ``?ids=`` read outright
(code 100, "The ids query parameter is deprecated"), so each object is read
at its own path. A launch names three objects, so that is three requests.

Same fields as the lists, so the rows parse into the same DTOs and the
mirror cannot tell which read wrote them.
"""

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

# "Object does not exist or you cannot see it". A deleted object is left out
# of the answer, the way the account lists leave it out. Read at its own
# path, a missing id comes back as 100/33 ("Unsupported get request") rather
# than 803 - the subcode, because a bare 100 is also a refused field.
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
    """These ads, with their creative's content wherever Meta will give it.

    An ad whose content Meta refuses to describe comes back with the
    creative's id alone. Its words and picture are missing from the mirror
    until a later read gets them; its status is not, and the status is what
    switching it on needs.
    """
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
