"""Turn the place names somebody typed into places a provider will target,
and seed the regions and cities the geography question offers."""

import hashlib
import logging
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from adskit import AudiencePort, registry
from adskit.errors import ProviderError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.common.cache import cache
from app.common.i18n import get_language
from app.modules.ads import draft as draft_field
from app.modules.ads import geo as geo_field
from app.modules.ads.constants import (
    MAX_GEO_LOOKUPS,
    MAX_GEO_PLACES,
    MIN_GEO_SEARCH,
    DraftSection,
    GeoAreaKind,
)
from app.modules.ads.exceptions import (
    ConnectionUnusable,
    NoAdAccount,
    PlaceSearchFailed,
)
from app.modules.ads.geo_catalogue import CATALOGUES, SeedName, key_for
from app.modules.ads.models import CampaignLaunch, GeoArea
from app.modules.ads.rows import fresh
from app.modules.ads.services.access import launch_account_and_token
from app.modules.ads.services.interests import request_estimate
from app.modules.ads.services.targeting import rebuild_targeting
from app.modules.businesses.models import Business
from core.targeting import GeoPlace

logger = logging.getLogger(__name__)
PARENTS_LOCK_PREFIX = "geo-parents:"
PARENTS_LOCK_SECONDS = 120
SEARCH_CACHE_PREFIX = "geo-search:"
SEARCH_CACHE_SECONDS = 86400


def place_query(typed: str) -> str:
    """What is worth asking the provider; empty while too little is typed."""
    query = " ".join(typed.split())
    return query if len(query) >= MIN_GEO_SEARCH else ""


def search_places(
    db: Session, *, launch: CampaignLaunch, query: str, country_code: str
) -> list[dict[str, str]]:
    """The places this word means, the given country's first, none dropped."""
    wanted = country_code.upper()
    return sorted(
        _found_places(db, launch=launch, query=query),
        key=lambda row: row["country_code"].upper() != wanted,
    )


def confirmed_places(
    db: Session, *, launch: CampaignLaunch, picked: list[dict[str, str]]
) -> list[dict[str, str]] | None:
    """The rows behind what the search offered; ``None`` when one was not offered.

    A key from the browser reaches a targeting spec only after the provider
    has answered it under that name again.
    """
    rows: list[dict[str, str]] = []
    for pick in picked:
        query = place_query(pick["name"])
        hits = _found_places(db, launch=launch, query=query) if query else []
        hit = next((row for row in hits if row["key"] == pick["key"]), None)
        if hit is None:
            return None
        rows.append(
            geo_field.place_row(
                key=hit["key"], name=hit["name"], kind=hit["kind"], parent=hit["parent"]
            )
        )
    return rows


def _found_places(
    db: Session, *, launch: CampaignLaunch, query: str
) -> list[dict[str, str]]:
    """One word's answer, kept whole: the save reads the search's own rows."""
    language = get_language()
    key = _search_key(provider=launch.provider, language=language, query=query)
    kept = _kept_search(key)
    if kept is not None:
        return kept
    try:
        _account, token = launch_account_and_token(db, launch=launch)
        found = registry.get(launch.provider).audiences.find_locations(
            query=query, country_code="", token=token, language=language
        )
    except ProviderError as exc:
        logger.warning("place search failed: %s", exc)
        raise PlaceSearchFailed from exc
    rows = [
        {
            "key": place.ref.id,
            "name": place.name,
            "kind": place.kind,
            "parent": place.parent_id,
            "country_code": place.country_code,
            "context": place.context,
        }
        for place in found
        if place.ref.id and place.kind in geo_field.KINDS
    ]
    _keep_search(key, rows)
    return rows


def _search_key(*, provider: str, language: str, query: str) -> str:
    digest = hashlib.sha256(query.casefold().encode()).hexdigest()
    return f"{SEARCH_CACHE_PREFIX}{provider}:{language}:{digest}"


def _kept_search(key: str) -> list[dict[str, str]] | None:
    try:
        return cache.get(key)
    except Exception:
        logger.warning("place search cache unreadable")
        return None


def _keep_search(key: str, rows: list[dict[str, str]]) -> None:
    try:
        cache.set(key, rows, SEARCH_CACHE_SECONDS)
    except Exception:
        logger.warning("place search cache unavailable")


def request_locations(db: Session, launch: CampaignLaunch) -> None:
    from app.common.db import on_commit
    from app.modules.ads.tasks import resolve_locations_task

    launch_id = str(launch.id)
    on_commit(db, lambda: resolve_locations_task.delay(launch_id))


def request_parents_if_unchecked(db: Session, launch: CampaignLaunch) -> bool:
    """Queue the region lookup for a proposal that is waiting on one."""
    chosen = draft_field.chosen(launch.draft, DraftSection.AUDIENCE)
    if not geo_field.unchecked_cities(chosen):
        return False
    try:
        added = cache.add(
            f"{PARENTS_LOCK_PREFIX}{launch.id}", "1", PARENTS_LOCK_SECONDS
        )
    except Exception:
        logger.warning("geo parents lock unavailable")
        added = True
    if not added:
        return False
    request_locations(db, launch)
    return True


def resolve_locations(db: Session, *, launch_id: UUID | str) -> str:
    """Look up one launch's typed place names. Returns a word for the log."""
    from app.modules.businesses.selectors import business_for_page

    launch = db.get(CampaignLaunch, UUID(str(launch_id)))
    if launch is None:
        return "gone"
    business = business_for_page(db, owner=launch.owner, page=launch.page)
    if business is None:
        return "profile_incomplete"
    chosen = draft_field.chosen(launch.draft, DraftSection.AUDIENCE)
    queries = geo_field.queries(chosen)[:MAX_GEO_LOOKUPS]
    waiting = [area for area in geo_field.areas(chosen) if not area["searched"]]
    unplaced = geo_field.unchecked_cities(chosen)
    if not queries and not waiting and not unplaced:
        return "nothing_typed"
    try:
        account, token = launch_account_and_token(db, launch=launch)
    except (NoAdAccount, ConnectionUnusable):
        _store(
            db,
            launch=launch,
            business=business,
            groups=_empty(queries),
            found={},
            parents={},
        )
        return "no_provider"
    audiences = registry.get(launch.provider).audiences
    try:
        groups = _search(
            audiences=audiences,
            queries=queries,
            country_code=business.country_code,
            token=token,
        )
        found = search_areas(
            audiences=audiences,
            areas=waiting,
            country_code=business.country_code,
            token=token,
        )
        parents = _parents(
            audiences=audiences,
            cities=unplaced,
            country_code=business.country_code,
            token=token,
        )
    except ProviderError as exc:
        logger.warning("location lookup failed for %s: %s", account.external_id, exc)
        return "provider_failed"
    _store(
        db,
        launch=launch,
        business=business,
        groups=groups,
        found=found,
        parents=parents,
    )
    return "resolved"


def _parents(
    *, audiences: AudiencePort, cities: list[GeoPlace], country_code: str, token: str
) -> dict[str, str]:
    parents: dict[str, str] = {}
    for city in cities:
        rows = (
            audiences.find_locations(
                query=city.name, country_code=country_code, token=token
            )
            if city.name
            else []
        )
        parents[city.key] = next(
            (row.parent_id for row in rows if row.ref.id == city.key), ""
        )
    return parents


def _search(
    *, audiences: AudiencePort, queries: list[str], country_code: str, token: str
) -> list[dict[str, Any]]:
    return [
        {
            "query": query,
            "places": [
                geo_field.place_row(
                    key=found.ref.id,
                    name=found.name,
                    kind=found.kind,
                    parent=found.parent_id,
                )
                for found in audiences.find_locations(
                    query=query, country_code=country_code, token=token
                )
                if found.ref.id
            ],
        }
        for query in queries
    ]


def search_areas(
    *,
    audiences: AudiencePort,
    areas: list[dict[str, Any]],
    country_code: str,
    token: str,
) -> dict[str, dict[str, str]]:
    return {
        str(area["area"]): _key_for(
            audiences=audiences, area=area, country_code=country_code, token=token
        )
        for area in areas
    }


def _key_for(
    *, audiences: AudiencePort, area: dict[str, Any], country_code: str, token: str
) -> dict[str, str]:
    wanted = {_folded(name) for name in area["names"]}
    for query in dict.fromkeys(area["names"]):
        rows = [
            found
            for found in audiences.find_locations(
                query=query, country_code=country_code, token=token
            )
            if found.ref.id
            and found.kind == area["kind"]
            and found.country_code.upper() == country_code.upper()
        ]
        named = [row for row in rows if _folded(row.name) in wanted]
        for hits in (named, rows):
            if len(hits) == 1:
                return {"key": hits[0].ref.id, "parent": hits[0].parent_id}
    return {"key": "", "parent": ""}


def _settled(area: dict[str, Any], found: dict[str, dict[str, str]]) -> dict[str, Any]:
    if area["searched"] or area["area"] not in found:
        return area
    return {**area, **found[area["area"]], "searched": True}


def _store(
    db: Session,
    *,
    launch: CampaignLaunch,
    business: Business,
    groups: list[dict[str, Any]],
    found: dict[str, dict[str, str]],
    parents: dict[str, str],
) -> None:
    """Write what came back, accept the certain ones, rebuild the spec."""
    draft = fresh(launch, "draft")
    chosen = dict(draft_field.chosen(draft, DraftSection.AUDIENCE) or {})
    geo = geo_field.stored(chosen)
    geo[geo_field.AREAS_KEY] = [
        _settled(area, found) for area in geo_field.areas(chosen)
    ]
    certain = _exact(groups=groups, country_code=business.country_code)
    keys = {row["key"] for row in geo["places"]}
    geo["places"] = (geo["places"] + [r for r in certain if r["key"] not in keys])[
        :MAX_GEO_PLACES
    ]
    geo["candidates"] = [group for group in groups if not _matched(group, certain)]
    geo["queries"] = []
    asked = [hit["key"] for hit in found.values() if hit["key"]]
    asked += [row["key"] for row in certain]
    geo = geo_field.with_parents(
        {geo_field.GEO_KEY: geo}, found={key: "" for key in asked} | parents
    )
    chosen[geo_field.GEO_KEY] = geo
    draft_field.choose(draft, DraftSection.AUDIENCE, chosen)
    rebuild_targeting(db, launch=launch, business=business)
    request_estimate(db, launch)
    db.commit()


def _exact(*, groups: list[dict[str, Any]], country_code: str) -> list[dict[str, Any]]:
    accepted: list[dict[str, Any]] = []
    for group in groups:
        wanted = _folded(str(group.get("query", "")))
        hits = [
            row
            for row in group.get("places", [])
            if _folded(str(row.get("name", ""))) == wanted
        ]
        if len(hits) == 1:
            accepted.append(hits[0])
    return accepted


def _matched(group: dict[str, Any], certain: list[dict[str, Any]]) -> bool:
    keys = {row["key"] for row in certain}
    return any(row.get("key") in keys for row in group.get("places", []))


def _empty(queries: list[str]) -> list[dict[str, Any]]:
    return [{"query": query, "places": []} for query in queries]


def _folded(value: str) -> str:
    return " ".join(value.split()).casefold()


# -- the catalogue --------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class GeoSyncResult:
    created: int
    total: int


def sync_geo_areas(db: Session) -> GeoSyncResult:
    """Create the regions and cities the seed file names, and nothing else."""
    known: dict[str, UUID] = dict(
        db.execute(select(GeoArea.key, GeoArea.id)).tuples().all()
    )
    regions = [row for row in _regions() if row.key not in known]
    db.add_all(regions)
    db.flush()
    known.update({row.key: row.id for row in regions})
    cities = [row for row in _cities(known) if row.key not in known]
    db.add_all(cities)
    db.commit()
    total = int(db.scalar(select(func.count(GeoArea.id))) or 0)
    return GeoSyncResult(created=len(regions) + len(cities), total=total)


def _regions() -> list[GeoArea]:
    rows = []
    for country_code, country in CATALOGUES.items():
        start = len(country.cities)
        for position, region in enumerate(country.regions, start=start):
            rows.append(
                _area(
                    country_code=country_code,
                    name=region.name,
                    kind=GeoAreaKind.REGION,
                    position=position,
                )
            )
    return rows


def _cities(known: dict[str, UUID]) -> list[GeoArea]:
    rows = []
    for country_code, country in CATALOGUES.items():
        for position, name in enumerate(country.cities):
            rows.append(
                _area(
                    country_code=country_code,
                    name=name,
                    kind=GeoAreaKind.CITY,
                    position=position,
                )
            )
        for region in country.regions:
            parent_id = known[key_for(country_code=country_code, name=region.name)]
            for position, name in enumerate(region.cities):
                rows.append(
                    _area(
                        country_code=country_code,
                        name=name,
                        kind=GeoAreaKind.CITY,
                        position=position,
                        parent_id=parent_id,
                    )
                )
    return rows


def _area(
    *,
    country_code: str,
    name: SeedName,
    kind: str,
    position: int,
    parent_id: UUID | None = None,
) -> GeoArea:
    return GeoArea(
        key=key_for(country_code=country_code, name=name),
        country_code=country_code,
        kind=str(kind),
        parent_id=parent_id,
        name_uz=name.uz,
        name_ru=name.ru,
        name_en=name.en,
        position=position,
    )
