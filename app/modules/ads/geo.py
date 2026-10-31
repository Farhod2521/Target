from typing import Any

from adskit import GeoKind

from core.targeting import GeoChoice, GeoMode, GeoOrigin, GeoPlace

GEO_KEY = "geo"
AREAS_KEY = "areas"
PARENTS_KEY = "parents_checked"
MODES: tuple[GeoMode, ...] = ("around", "places", "country")
KINDS: tuple[GeoKind, ...] = ("city", "region", "country")


def empty_geo() -> dict[str, Any]:
    return {
        "mode": "country",
        "places": [],
        "queries": [],
        "candidates": [],
        "lat": "",
        "lng": "",
        "country_code": "",
        "origin": "derived",
        "address": "",
        AREAS_KEY: [],
        PARENTS_KEY: [],
    }


def stored(chosen: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(chosen, dict):
        return empty_geo()
    found = chosen.get(GEO_KEY)
    return {**empty_geo(), **found} if isinstance(found, dict) else empty_geo()


def to_choice(
    chosen: dict[str, Any] | None, *, radius_km: int | None = None
) -> GeoChoice:
    raw = stored(chosen)
    return GeoChoice(
        mode=_mode(raw.get("mode")),
        places=_distinct(
            [
                _place(item)
                for item in _rows(raw.get("places"))
                + [area for area in areas(chosen) if area["key"]]
            ]
        ),
        lat=str(raw.get("lat") or ""),
        lng=str(raw.get("lng") or ""),
        radius_km=radius_km,
        country_code=str(raw.get("country_code") or ""),
        origin="chosen" if raw.get("origin") == "chosen" else "derived",
    )


def from_choice(choice: GeoChoice) -> dict[str, Any]:
    return {
        **empty_geo(),
        "mode": choice.mode,
        "places": [_row(place) for place in choice.places],
        "lat": choice.lat,
        "lng": choice.lng,
        "country_code": choice.country_code,
        "origin": choice.origin,
    }


def known_places(chosen: dict[str, Any] | None) -> list[dict[str, str]]:
    seen: dict[str, dict[str, str]] = {}
    for row in _rows(stored(chosen).get("places")) + candidates(chosen):
        place = _place(row)
        if place.is_usable and place.key not in seen:
            seen[place.key] = _row(place)
    return list(seen.values())


def candidates(chosen: dict[str, Any] | None) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for group in _rows(stored(chosen).get("candidates")):
        rows.extend(_row(_place(item)) for item in _rows(group.get("places")))
    return rows


def queries(chosen: dict[str, Any] | None) -> list[str]:
    raw = stored(chosen).get("queries")
    return (
        [str(item) for item in raw if str(item).strip()]
        if isinstance(raw, list)
        else []
    )


def unmatched(chosen: dict[str, Any] | None) -> list[str]:
    found = {
        str(group.get("query", ""))
        for group in _rows(stored(chosen).get("candidates"))
        if group.get("places")
    }
    searched = _rows(stored(chosen).get("candidates"))
    return [
        str(group.get("query", ""))
        for group in searched
        if str(group.get("query", "")) not in found
    ]


def areas(chosen: dict[str, Any] | None) -> list[dict[str, Any]]:
    return [_area(row) for row in _rows(stored(chosen).get(AREAS_KEY))]


def area_row(*, area: str, name: str, kind: str, names: list[str]) -> dict[str, Any]:
    return _area({"area": area, "name": name, "kind": kind, "names": names, "key": ""})


def waiting_names(chosen: dict[str, Any] | None) -> list[str]:
    waiting = [row["name"] for row in areas(chosen) if not row["searched"]]
    unplaced = [place.name or place.key for place in unchecked_cities(chosen)]
    return waiting + queries(chosen) + unplaced


def unchecked_cities(chosen: dict[str, Any] | None) -> list[GeoPlace]:
    raw = stored(chosen)
    if raw.get("mode") != "places":
        return []
    places = to_choice(chosen).usable_places
    if not any(place.kind == "region" for place in places):
        return []
    checked = {str(key) for key in raw.get(PARENTS_KEY) or []}
    return [
        place
        for place in places
        if place.kind == "city" and (not place.parent) and (place.key not in checked)
    ]


def with_parents(chosen: dict[str, Any] | None, *, found: dict[str, str]) -> dict:
    raw = stored(chosen)

    def placed(row: dict[str, Any]) -> dict[str, Any]:
        key = str(row.get("key") or "")
        if key in found and row.get("kind") == "city" and (not row.get("parent")):
            return {**row, "parent": found[key]}
        return row

    return {
        **raw,
        "places": [placed(row) for row in _rows(raw.get("places"))],
        AREAS_KEY: [placed(row) for row in _rows(raw.get(AREAS_KEY))],
        PARENTS_KEY: list(dict.fromkeys([*(raw.get(PARENTS_KEY) or []), *found])),
    }


def missing_names(chosen: dict[str, Any] | None) -> list[str]:
    missing = [
        row["name"] for row in areas(chosen) if row["searched"] and (not row["key"])
    ]
    return missing + unmatched(chosen)


def unresolved(chosen: dict[str, Any] | None) -> list[str]:
    if stored(chosen).get("mode") != "places":
        return []
    return waiting_names(chosen) + missing_names(chosen)


def place_row(*, key: str, name: str, kind: str, parent: str = "") -> dict[str, str]:
    return _row(GeoPlace(key=key, name=name, kind=_kind(kind), parent=parent))


def _rows(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _distinct(places: list[GeoPlace]) -> tuple[GeoPlace, ...]:
    seen: dict[tuple[str, str], GeoPlace] = {}
    for place in places:
        seen.setdefault((place.kind, place.key), place)
    return tuple(seen.values())


def _place(row: dict[str, Any]) -> GeoPlace:
    return GeoPlace(
        key=str(row.get("key") or ""),
        name=str(row.get("name") or ""),
        kind=_kind(row.get("kind")),
        parent=str(row.get("parent") or ""),
    )


def _row(place: GeoPlace) -> dict[str, str]:
    return {
        "key": place.key,
        "name": place.name,
        "kind": place.kind,
        "parent": place.parent,
    }


def _area(row: dict[str, Any]) -> dict[str, Any]:
    names = row.get("names")
    return {
        "area": str(row.get("area") or ""),
        "name": str(row.get("name") or ""),
        "kind": _kind(row.get("kind")),
        "names": [str(item) for item in names if str(item).strip()]
        if isinstance(names, list)
        else [],
        "key": str(row.get("key") or ""),
        "parent": str(row.get("parent") or ""),
        "searched": bool(row.get("searched")),
    }


def _mode(value: Any) -> GeoMode:
    return value if value in MODES else "country"


def _kind(value: Any) -> GeoKind:
    return value if value in KINDS else "other"


def origin_of(chosen: dict[str, Any] | None) -> GeoOrigin:
    return "chosen" if stored(chosen).get("origin") == "chosen" else "derived"
