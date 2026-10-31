"""What the owner accepted on the proposal, one section at a time."""

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.modules.ads import audiences as audience_field
from app.modules.ads import draft as draft_field
from app.modules.ads import geo as geo_field
from app.modules.ads import naming
from app.modules.ads.constants import (
    CUSTOM_QUESTION_PREFIX,
    GEO_COUNTRY,
    GEO_PLACES,
    LAUNCH_RELATED_TYPE,
    MAX_GEO_LOOKUPS,
    MAX_GEO_PLACES,
    MAX_OPTIONS,
    NEW_ROW_PREFIX,
    OPTIONS_PENDING,
    QUESTION_TYPES,
    DraftSection,
    InterestSource,
)
from app.modules.ads.exceptions import DraftNotReady, NoInterestChosen, UnknownVariant
from app.modules.ads.models import CampaignLaunch, LaunchCreative
from app.modules.ads.rows import fresh
from app.modules.ads.selectors.audiences_chosen import picked_areas
from app.modules.ads.services.sections import request_options
from app.modules.ads.services.targeting import (
    rebuild_targeting,
    remember_terms,
    suggested_geo,
)
from app.modules.audit.constants import EventName
from app.modules.businesses.models import Business
from core.targeting.quality import wants_quality


def _require_draft(launch: CampaignLaunch) -> None:
    if not launch.draft:
        raise DraftNotReady


def save_audience(
    db: Session,
    *,
    launch: CampaignLaunch,
    business: Business,
    age_min: int,
    age_max: int,
    genders: list[int],
    radius_km: int | None,
    targeting_mode: str,
    placement_mode: str,
    lead_buying: str,
    audiences: dict[str, list[dict[str, str]]],
    geo_mode: str,
    place_keys: list[str],
    added: list[str],
    area_keys: tuple[str, ...] | list[str] = (),
    pin: tuple[str, str] = ("", ""),
    picked: tuple[dict[str, str], ...] | list[dict[str, str]] = (),
    address: str = "",
    placement_positions: dict[str, list[str]] | None = None,
) -> bool:
    """The numbers, the mode and the geography, as corrected."""
    from app.modules.businesses.services import remember_location

    _require_draft(launch)
    draft = fresh(launch, "draft")
    previous = draft_field.chosen(draft, DraftSection.AUDIENCE) or {}
    geo, pending = _geo_answer(
        db,
        launch=launch,
        business=business,
        previous=previous,
        mode=geo_mode,
        place_keys=place_keys,
        added=added,
        area_keys=list(area_keys),
        pin=pin,
        picked=list(picked),
        address=address,
    )
    draft_field.choose(
        draft,
        DraftSection.AUDIENCE,
        {
            "age_min": age_min,
            "age_max": age_max,
            "genders": genders,
            "radius_km": radius_km,
            "targeting_mode": targeting_mode,
            "placement_mode": placement_mode,
            "placement_positions": placement_positions or {},
            audience_field.AUDIENCES_KEY: audiences,
            geo_field.GEO_KEY: geo,
            "reason": previous.get("reason", ""),
        },
    )
    draft_field.set_source(draft, draft_field.AUDIENCE_MODE, draft_field.BY_OWNER)
    draft_field.set_source(draft, draft_field.PLACEMENT_MODE, draft_field.BY_OWNER)
    remember_location(
        db,
        business=business,
        lat=str(geo.get("lat") or ""),
        lng=str(geo.get("lng") or ""),
        city=_first_town(geo),
    )
    launch.buy_qualified_leads = wants_quality(lead_buying)
    rebuild_targeting(db, launch=launch, business=business)
    db.flush()
    return pending


def _geo_answer(
    db: Session,
    *,
    launch: CampaignLaunch,
    business: Business,
    previous: dict[str, Any],
    mode: str,
    place_keys: list[str],
    added: list[str],
    area_keys: list[str],
    pin: tuple[str, str],
    picked: list[dict[str, str]],
    address: str,
) -> tuple[dict[str, Any], bool]:
    """One geography answer, and whether it still needs the provider."""
    areas = picked_areas(
        db,
        keys=area_keys,
        previous=geo_field.areas(previous),
        country_code=business.country_code,
        limit=MAX_GEO_PLACES,
    )
    keys = set(place_keys)
    known = geo_field.known_places(previous)
    taken = {(area["kind"], area["key"]) for area in areas if area["key"]}
    kept = [
        row
        for row in [*known, *picked]
        if (row.get("key") in keys or row in picked)
        and (row.get("kind"), row.get("key")) not in taken
    ][: MAX_GEO_PLACES - len(areas)]
    queries = _fresh_queries(added=added, known=known)
    carried = geo_field.stored(previous)
    placed = _pin(db, launch=launch, business=business, carried=carried, given=pin)
    named = bool(kept or queries or areas)
    answer = {
        **geo_field.empty_geo(),
        "mode": mode if mode != GEO_PLACES or named else GEO_COUNTRY,
        "places": kept,
        "queries": queries,
        "candidates": [],
        geo_field.AREAS_KEY: areas,
        "lat": placed[0],
        "lng": placed[1],
        "country_code": business.country_code,
        "origin": "chosen",
        "address": address,
        geo_field.PARENTS_KEY: carried.get(geo_field.PARENTS_KEY) or [],
    }
    pending = (
        bool(queries)
        or any(not area["searched"] for area in areas)
        or bool(geo_field.unchecked_cities({geo_field.GEO_KEY: answer}))
    )
    return answer, pending


def _first_town(geo: dict[str, Any]) -> str:
    for row in [*(geo.get("places") or []), *(geo.get(geo_field.AREAS_KEY) or [])]:
        if isinstance(row, dict) and row.get("kind") == "city":
            return str(row.get("name") or "")
    return ""


def _fresh_queries(*, added: list[str], known: list[dict[str, Any]]) -> list[str]:
    seen = {str(row.get("name", "")).casefold() for row in known}
    found: list[str] = []
    for name in added:
        folded = name.casefold()
        if folded and folded not in seen:
            seen.add(folded)
            found.append(name)
    return found[:MAX_GEO_LOOKUPS]


def _pin(
    db: Session,
    *,
    launch: CampaignLaunch,
    business: Business,
    carried: dict[str, Any],
    given: tuple[str, str],
) -> tuple[str, str]:
    if all(given):
        return given
    lat, lng = str(carried.get("lat") or ""), str(carried.get("lng") or "")
    if lat and lng:
        return lat, lng
    offered = suggested_geo(db, owner=launch.owner, business=business, page=launch.page)
    return offered.lat, offered.lng


def save_interests(
    db: Session,
    *,
    launch: CampaignLaunch,
    business: Business,
    queries: list[str],
    added: list[str],
) -> None:
    """The ticked boxes plus anything typed in."""
    _require_draft(launch)
    draft = fresh(launch, "draft")
    pool = list(draft_field.proposal(draft, DraftSection.INTERESTS) or [])
    pooled = {str(p.get("query", "")) for p in pool}
    pool += [
        item
        for item in draft_field.chosen(draft, DraftSection.INTERESTS) or []
        if str(item.get("query", "")) not in pooled
    ]
    by_query = {str(item.get("query", "")): item for item in pool}
    confirmed = {
        str(item.get("query", "")): str(item.get("external_id", ""))
        for item in draft_field.chosen(draft, DraftSection.INTERESTS) or []
    }
    chosen = [
        {
            "label": str(by_query[query].get("label", query)),
            "query": query,
            "external_id": confirmed.get(query, ""),
        }
        for query in queries
        if query in by_query
    ]
    typed = [
        {"label": name.strip(), "query": name.strip(), "external_id": ""}
        for name in added
        if name.strip()
    ]
    chosen += _without_duplicates(typed, seen={item["query"] for item in chosen})
    if not chosen:
        raise NoInterestChosen
    draft_field.choose(draft, DraftSection.INTERESTS, chosen)
    rebuild_targeting(db, launch=launch, business=business)
    db.flush()
    remember_terms(db, launch=launch, items=chosen, source=InterestSource.AI)
    remember_terms(db, launch=launch, items=typed, source=InterestSource.USER)


def save_traits(
    db: Session,
    *,
    launch: CampaignLaunch,
    business: Business,
    traits: list[dict[str, str]],
) -> None:
    _require_draft(launch)
    draft = fresh(launch, "draft")
    draft_field.choose(draft, DraftSection.TRAITS, traits)
    rebuild_targeting(db, launch=launch, business=business)
    db.flush()


def save_creative(
    db: Session,
    *,
    launch: CampaignLaunch,
    business: Business,
    position: int,
    primary_text: str,
    headline: str,
    description: str,
    ad_name: str = "",
) -> None:
    """One variant's words, as edited. Nothing here reaches the targeting spec."""
    from app.modules.audit.services import emit

    _require_draft(launch)
    row = db.scalar(
        select(LaunchCreative).where(
            LaunchCreative.launch_id == launch.id, LaunchCreative.position == position
        )
    )
    if row is None:
        raise UnknownVariant
    previous = _words_of(row)
    previous_name = row.ad_name
    row.primary_text = primary_text.strip()
    row.headline = headline.strip()
    row.description = description.strip()
    row.ad_name = _typed_name(
        typed=ad_name,
        generated=naming.ad_name(launch=launch, business=business, position=position),
    )
    words_changed = _words_of(row) != previous
    if not words_changed and row.ad_name == previous_name:
        return
    db.flush()
    if words_changed:
        emit(
            db,
            owner_id=launch.owner_id,
            name=EventName.LAUNCH_COPY_EDITED,
            aggregate_type=LAUNCH_RELATED_TYPE,
            aggregate_id=launch.id,
            payload={
                "position": position,
                "previous": previous,
                "words": _words_of(row),
            },
        )


def _words_of(row: LaunchCreative) -> dict[str, str]:
    return {
        "primary_text": row.primary_text,
        "headline": row.headline,
        "description": row.description,
    }


def _typed_name(*, typed: str, generated: str) -> str:
    wanted = typed.strip()
    return "" if wanted == generated else wanted


def save_questions(
    db: Session,
    *,
    launch: CampaignLaunch,
    business: Business,
    kinds: list[str],
    added: list[str],
    options: dict[str, list[str]] | None = None,
    labels: dict[str, str] | None = None,
    order: list[str] | None = None,
    text_only: list[str] | None = None,
) -> None:
    """The ticked questions plus anything typed in."""
    _require_draft(launch)
    draft = fresh(launch, "draft")
    proposed = draft_field.proposal(draft, DraftSection.FORM) or []
    chosen_before = draft_field.chosen(draft, DraftSection.FORM) or []
    proposed_kinds = {str(p.get("kind", "")) for p in proposed}
    pool = list(proposed) + [
        item
        for item in chosen_before
        if str(item.get("kind", "")) not in proposed_kinds
    ]
    kept = [dict(item) for item in pool if str(item.get("kind", "")) in kinds]
    _reword(kept, labels or {})
    numbered = _typed_questions(
        added,
        taken={str(item.get("kind", "")) for item in pool},
        asked={str(item.get("label", "")).casefold() for item in kept},
    )
    typed = [item for _index, item in numbered]
    kept += typed
    renamed = {f"{NEW_ROW_PREFIX}{index}": item["kind"] for index, item in numbered}
    if order:
        kept = _in_order(kept, [renamed.get(token, token) for token in order])
    given = {renamed.get(key, key): value for key, value in (options or {}).items()}
    for item in kept:
        kind = str(item.get("kind", ""))
        if kind in QUESTION_TYPES:
            item.pop("options", None)
            continue
        item["options"] = [str(value) for value in given.get(kind, [])][:MAX_OPTIONS]
    in_words = {renamed.get(token, token) for token in text_only or []}
    asking = [
        item for item in typed if not item["options"] and item["kind"] not in in_words
    ]
    for item in asking:
        item[OPTIONS_PENDING] = True
    draft_field.choose(draft, DraftSection.FORM, draft_field.with_phone(kept))
    refs = fresh(launch, "created_refs")
    refs.pop("form", None)
    db.flush()
    request_options(
        db, launch=launch, kinds=[str(item.get("kind", "")) for item in asking]
    )


def _reword(kept: list[dict[str, Any]], labels: dict[str, str]) -> None:
    for item in kept:
        kind = str(item.get("kind", ""))
        label = labels.get(kind, "").strip()
        if label and kind not in QUESTION_TYPES:
            item["label"] = label


def _in_order(kept: list[dict[str, Any]], kinds: list[str]) -> list[dict[str, Any]]:
    rank = {kind: index for index, kind in enumerate(kinds)}
    return sorted(kept, key=lambda item: rank.get(str(item.get("kind", "")), len(rank)))


def _typed_questions(
    added: list[str], *, taken: set[str], asked: set[str]
) -> list[tuple[int, dict[str, Any]]]:
    numbers = [
        int(kind.removeprefix(CUSTOM_QUESTION_PREFIX))
        for kind in taken
        if kind.startswith(CUSTOM_QUESTION_PREFIX)
        and kind.removeprefix(CUSTOM_QUESTION_PREFIX).isdigit()
    ]
    next_number = max(numbers, default=0) + 1
    built: list[tuple[int, dict[str, Any]]] = []
    for index, line in enumerate(added):
        label = line.strip()
        if not label or label.casefold() in asked:
            continue
        asked.add(label.casefold())
        built.append(
            (index, {"kind": f"{CUSTOM_QUESTION_PREFIX}{next_number}", "label": label})
        )
        next_number += 1
    return built


def _without_duplicates(
    items: list[dict[str, str]], *, seen: set[str]
) -> list[dict[str, str]]:
    kept: list[dict[str, str]] = []
    for item in items:
        if item["query"] in seen:
            continue
        seen.add(item["query"])
        kept.append(item)
    return kept
