from collections.abc import Iterable, Mapping
from typing import Any
from uuid import UUID

AUDIENCES_KEY = "audiences"
INCLUDED = "included"
EXCLUDED = "excluded"
SIDES: tuple[str, ...] = (INCLUDED, EXCLUDED)
INCLUDE_ROLE = "include"
EXCLUDE_ROLE = "exclude"
ROLES: Mapping[str, str] = {INCLUDE_ROLE: INCLUDED, EXCLUDE_ROLE: EXCLUDED}
FIELD_PREFIX = "audience-"


def empty_audiences() -> dict[str, list[dict[str, str]]]:
    return {INCLUDED: [], EXCLUDED: []}


def stored(chosen: dict[str, Any] | None) -> dict[str, list[dict[str, str]]]:
    if not isinstance(chosen, dict):
        return empty_audiences()
    saved = chosen.get(AUDIENCES_KEY)
    if not isinstance(saved, dict):
        return empty_audiences()
    return {side: _rows(saved.get(side)) for side in SIDES}


def roles(chosen: dict[str, Any] | None) -> dict[str, str]:
    saved = stored(chosen)
    picked = {row["key"]: INCLUDE_ROLE for row in saved[INCLUDED]}
    picked.update({row["key"]: EXCLUDE_ROLE for row in saved[EXCLUDED]})
    return picked


def chosen_keys(chosen: dict[str, Any] | None) -> list[str]:
    saved = stored(chosen)
    return [row["key"] for side in SIDES for row in saved[side]]


def from_roles(
    picked: Mapping[str, str], *, labels: Mapping[str, str]
) -> dict[str, list[dict[str, str]]]:
    answer = empty_audiences()
    for key, role in picked.items():
        side = ROLES.get(role)
        if side is None:
            continue
        answer[side].append({"key": key, "label": labels.get(key, "")})
    return answer


def field_name(key: str) -> str:
    return f"{FIELD_PREFIX}{key}"


def roles_from_post(
    data: Mapping[str, Any], *, keys: Iterable[str], prefix: str = ""
) -> dict[str, str]:
    picked: dict[str, str] = {}
    for key in keys:
        role = str(data.get(f"{prefix}{field_name(key)}", "") or "")
        if role in ROLES:
            picked[key] = role
    return picked


def _rows(value: Any) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    seen: set[str] = set()
    kept: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        key = str(item.get("key", ""))
        if key in seen or not _is_key(key):
            continue
        seen.add(key)
        kept.append({"key": key, "label": str(item.get("label", ""))})
    return kept


def _is_key(value: str) -> bool:
    try:
        UUID(value)
    except ValueError:
        return False
    return True


__all__ = [
    "AUDIENCES_KEY",
    "EXCLUDED",
    "EXCLUDE_ROLE",
    "FIELD_PREFIX",
    "INCLUDED",
    "INCLUDE_ROLE",
    "ROLES",
    "SIDES",
    "chosen_keys",
    "empty_audiences",
    "field_name",
    "from_roles",
    "roles",
    "roles_from_post",
    "stored",
]
