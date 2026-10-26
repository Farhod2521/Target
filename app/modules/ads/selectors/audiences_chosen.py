"""The audiences, interests and places a launch chose, as the domain needs them."""

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.modules.accounts.models import User
from app.modules.ads import audiences as audience_field
from app.modules.ads import draft as draft_field
from app.modules.ads import geo as geo_field
from app.modules.ads.constants import DraftSection, GeoAreaKind, LaunchStatus
from app.modules.ads.models import CampaignLaunch, GeoArea, InterestTerm
from core.targeting import AudienceChoice, AudienceRef

KNOWN_TERMS_LIMIT = 15
LAUNCH_HISTORY = 20
APOSTROPHES = ("'", "`", *(chr(code) for code in (8216, 8217, 699, 700)))


def chosen_audiences(
    db: Session, *, launch: CampaignLaunch, special_ad_category: str = ""
) -> AudienceChoice:
    """Who this launch is aimed at, and what it has lost since it chose."""
    from app.modules.integrations.selectors.audiences import targets_by_key

    chosen = draft_field.chosen(launch.draft, DraftSection.AUDIENCE) or {}
    saved = audience_field.stored(chosen)
    found = targets_by_key(
        db,
        owner=launch.owner,
        keys=audience_field.chosen_keys(chosen),
        special_ad_category=special_ad_category,
    )
    sides: dict[str, list[AudienceRef]] = {side: [] for side in audience_field.SIDES}
    dropped: list[str] = []
    for side in audience_field.SIDES:
        for row in saved[side]:
            option = found.get(row["key"])
            if option is None:
                dropped.append(row["label"])
                continue
            sides[side].append(
                AudienceRef(
                    external_id=option.external_id,
                    label=option.label,
                    is_lookalike=option.is_lookalike,
                    is_usable=option.is_usable,
                )
            )
    return AudienceChoice(
        included=tuple(sides[audience_field.INCLUDED]),
        excluded=tuple(sides[audience_field.EXCLUDED]),
        dropped=tuple(dropped),
    )


# -- interests the provider confirmed -------------------------------------------------


@dataclass(frozen=True, slots=True)
class KnownTerm:
    label: str
    query: str
    audience_size: int | None = None


def launched_queries(db: Session, *, owner: User, provider: str) -> set[str]:
    """The interest names that went into a campaign this product created."""
    rows = db.scalars(
        select(CampaignLaunch.draft)
        .where(
            CampaignLaunch.owner_id == owner.id,
            CampaignLaunch.provider == provider,
            CampaignLaunch.status == str(LaunchStatus.CREATED),
        )
        .order_by(CampaignLaunch.created_at.desc())
        .limit(LAUNCH_HISTORY)
    )
    found: set[str] = set()
    for draft in rows:
        if not isinstance(draft, dict):
            continue
        chosen = draft_field.chosen(draft, DraftSection.INTERESTS)
        if not isinstance(chosen, list):
            continue
        for item in chosen:
            query = str(item.get("query", "")).strip() if isinstance(item, dict) else ""
            if query:
                found.add(query)
    return found


def confirmed_terms(
    db: Session, *, owner: User, provider: str, limit: int = KNOWN_TERMS_LIMIT
) -> tuple[KnownTerm, ...]:
    ran = launched_queries(db, owner=owner, provider=provider)
    if not ran:
        return ()
    rows = db.scalars(
        select(InterestTerm)
        .where(
            InterestTerm.owner_id == owner.id,
            InterestTerm.provider == provider,
            InterestTerm.query.in_(ran),
            InterestTerm.external_id != "",
        )
        .order_by(InterestTerm.confirmed_at.desc().nulls_last(), InterestTerm.label)
        .limit(limit)
    )
    return tuple(
        KnownTerm(
            label=row.label or row.query,
            query=row.query,
            audience_size=row.audience_size,
        )
        for row in rows
    )


# -- places ----------------------------------------------------------------------------


def area_options(db: Session, *, country_code: str) -> list[dict[str, str]]:
    """Every active place in one country, in the order the picker draws it."""
    if not country_code:
        return []
    rows = db.scalars(
        select(GeoArea)
        .where(
            GeoArea.country_code == country_code.upper(), GeoArea.is_active.is_(True)
        )
        .order_by(GeoArea.position, GeoArea.name_uz)
    )
    roots: list[GeoArea] = []
    children: dict[UUID, list[GeoArea]] = {}
    for row in rows:
        if row.parent_id is None:
            roots.append(row)
        else:
            children.setdefault(row.parent_id, []).append(row)
    options: list[dict[str, str]] = []
    for root in roots:
        options.append(_option(root, parent=""))
        options.extend(
            _option(city, parent=root.key) for city in children.get(root.id, [])
        )
    return options


def picked_areas(
    db: Session,
    *,
    keys: list[str],
    previous: list[dict[str, Any]],
    country_code: str,
    limit: int,
) -> list[dict[str, Any]]:
    """The ticked places, as the geography answer stores them."""
    wanted = list(dict.fromkeys(key for key in keys if key))
    if not wanted:
        return []
    rows = {
        row.key: row
        for row in db.scalars(
            select(GeoArea)
            .where(
                GeoArea.key.in_(wanted), GeoArea.country_code == country_code.upper()
            )
            .options(selectinload(GeoArea.parent))
        )
    }
    regions = {key for key, row in rows.items() if row.kind == GeoAreaKind.REGION}
    carried = {row["area"]: row for row in previous}
    picked: list[dict[str, Any]] = []
    for key in wanted:
        row = rows.get(key)
        if row is None or (row.parent is not None and row.parent.key in regions):
            continue
        picked.append(
            carried.get(key)
            or geo_field.area_row(
                area=row.key,
                name=row.name,
                kind=row.kind,
                names=[row.name_en, row.name_ru, row.name_uz],
            )
        )
    return picked[:limit]


def _option(row: GeoArea, *, parent: str) -> dict[str, str]:
    return {
        "key": row.key,
        "name": row.name,
        "kind": row.kind,
        "parent": parent,
        "search": " ".join(
            _folded(name) for name in (row.name_uz, row.name_ru, row.name_en)
        ),
    }


def _folded(value: str) -> str:
    for mark in APOSTROPHES:
        value = value.replace(mark, "")
    return " ".join(value.lower().split())
