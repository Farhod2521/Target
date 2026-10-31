"""What a running audience's form asks the network: who may be picked, and how many.

Every call here reads and none writes. A row the owner adds must have come
from these searches, so a save asks again by name, as the place search does.
"""

import hashlib
import logging
from collections.abc import Callable, Mapping, Sequence
from typing import Any, Final

from adskit import registry
from adskit.dto import ReachDTO
from adskit.errors import PortNotAvailable, ProviderError
from adskit.refs import ExternalRef, ProviderName
from sqlalchemy.orm import Session

from app.common.cache import cache
from app.modules.ads.constants import ManagedLevel
from app.modules.ads.exceptions import PlaceSearchFailed
from app.modules.ads.models import AdSet, Campaign
from app.modules.ads.services.access import target_account_and_token
from app.modules.ads.services.interests import sized
from core.targeting.revise import Detail

logger = logging.getLogger(__name__)
SEARCH_CACHE_SECONDS: Final = 86400
LOCALE_SWEEP: Final = ("a", "e", "i", "o", "u")
DETAIL_KEYS: Final[dict[str, str]] = {
    "interest": "interests",
    "behaviour": "behaviors",
    "life_event": "life_events",
}


def _kept(key: str, ask: Callable[[], list[dict[str, Any]]]) -> list[dict[str, Any]]:
    held = cache.get(key)
    if held is not None:
        return list(held)
    rows = ask()
    cache.set(key, rows, SEARCH_CACHE_SECONDS)
    return rows


def _key(name: str, provider: str, query: str) -> str:
    digest = hashlib.sha256(query.casefold().encode()).hexdigest()
    return f"audience-search:{name}:{provider}:{digest}"


def _token(campaign: Campaign) -> str:
    _account, token = target_account_and_token(
        target=campaign, level=ManagedLevel.CAMPAIGN
    )
    return token


def search_detail(
    db: Session, *, campaign: Campaign, query: str
) -> list[dict[str, Any]]:
    """Interests, behaviours and life events a person may pick for this word."""

    def ask() -> list[dict[str, Any]]:
        found = registry.get(campaign.provider).audiences.search_detail(
            query=query, token=_token(campaign)
        )
        return [
            {
                "id": row.ref.id,
                "name": row.name,
                "kind": DETAIL_KEYS[row.kind],
                "path": " · ".join(row.path),
                "lower": row.audience_lower,
                "upper": row.audience_upper,
            }
            for row in found
            if row.kind in DETAIL_KEYS
        ]

    return _searched(lambda: _kept(_key("detail", campaign.provider, query), ask))


def search_locales(*, campaign: Campaign, query: str) -> list[dict[str, Any]]:
    """The languages the network targets by, under this word."""

    def ask() -> list[dict[str, Any]]:
        found = registry.get(campaign.provider).audiences.search_locales(
            query=query, token=_token(campaign)
        )
        return [{"id": row.key, "name": row.name} for row in found]

    return _searched(lambda: _kept(_key("locale", campaign.provider, query), ask))


def locale_names(*, campaign: Campaign, keys: Sequence[int]) -> dict[int, str]:
    """The names of the languages an audience holds, which its spec gives as numbers.

    Meta has no read by number, so the catalogue is searched a vowel at a time
    and kept. A failure only costs the names: the form goes on with the numbers.
    """
    wanted = set(keys)
    names: dict[int, str] = {}
    for letter in LOCALE_SWEEP:
        if wanted <= set(names):
            break
        try:
            rows = search_locales(campaign=campaign, query=letter)
        except Exception as exc:
            logger.info("language names unavailable: %s", exc)
            break
        names |= {row["id"]: row["name"] for row in rows}
    return {key: names[key] for key in wanted if key in names}


def _searched(read: Callable[[], list[dict[str, Any]]]) -> list[dict[str, Any]]:
    try:
        return read()
    except PortNotAvailable:
        return []
    except ProviderError as exc:
        logger.warning("audience search failed: %s", exc)
        raise PlaceSearchFailed from exc


def confirmed_detail(
    db: Session, *, campaign: Campaign, picked: Sequence[Mapping[str, str]]
) -> tuple[Detail, ...] | None:
    """What the search offered under these names; ``None`` when one was not."""
    rows: list[Detail] = []
    for pick in picked:
        hits = search_detail(db, campaign=campaign, query=pick["name"])
        hit = next(
            (
                row
                for row in hits
                if row["id"] == pick["id"] and row["kind"] == pick["kind"]
            ),
            None,
        )
        if hit is None:
            return None
        rows.append(Detail(id=hit["id"], name=hit["name"], kind=hit["kind"]))
    return tuple(rows)


def estimated_reach(
    *, campaign: Campaign, group: AdSet, targeting: dict[str, Any]
) -> ReachDTO:
    """How many people this spec would reach, asked of the network and not saved."""
    account, token = target_account_and_token(
        target=campaign, level=ManagedLevel.CAMPAIGN
    )
    return sized(
        registry.get(campaign.provider).audiences,
        account=ExternalRef(
            provider=ProviderName(campaign.provider),
            level="account",
            id=account.external_id,
        ),
        targeting=targeting,
        optimization_goal=group.optimization_goal_raw,
        token=token,
    )


__all__ = [
    "confirmed_detail",
    "estimated_reach",
    "locale_names",
    "search_detail",
    "search_locales",
]
