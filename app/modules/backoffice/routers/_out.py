"""How office rows are drawn as JSON, shared by every office router."""

from typing import Any

from app.modules.accounts.models import User
from app.modules.backoffice import selectors
from app.modules.backoffice.models import StaffAction


def person_out(user: User | None) -> dict[str, Any] | None:
    if user is None:
        return None
    return {
        "id": str(user.id),
        "name": user.full_name or user.email,
        "email": user.email,
    }


def trace_out(row: StaffAction) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "created_at": row.created_at,
        "kind": row.kind,
        "kind_label": selectors.kind_label(row.kind),
        "reason": row.reason,
        "detail": row.detail or {},
        "actor": person_out(row.actor),
    }


def choices(
    pairs: list[tuple[str, str]] | tuple[tuple[str, str], ...],
) -> list[dict[str, str]]:
    return [{"value": value, "label": label} for value, label in pairs]


def amounts(pairs: tuple[tuple[str, int], ...]) -> list[dict[str, Any]]:
    return [{"currency": currency, "amount_minor": minor} for currency, minor in pairs]
