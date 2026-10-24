"""The other direction: Meta calling us when a form is filled in."""

import hmac
from dataclasses import dataclass
from datetime import UTC, datetime
from hashlib import sha256
from typing import Any, Final

SIGNATURE_PREFIX: Final = "sha256="

SUBSCRIBE_MODE: Final = "subscribe"

LEADGEN_FIELD: Final = "leadgen"

PAGE_OBJECT: Final = "page"


@dataclass(frozen=True, slots=True)
class LeadNotice:
    """One "a form was filled in" from Meta. Not the lead."""

    page_external_id: str
    leadgen_external_id: str
    form_external_id: str = ""
    ad_external_id: str = ""
    adset_external_id: str = ""
    created_at: datetime | None = None


def verify_signature(*, body: bytes, header: str, app_secret: str) -> bool:
    """Whether this body really came from Meta."""
    if not app_secret or not header.startswith(SIGNATURE_PREFIX):
        return False

    expected = hmac.new(app_secret.encode(), body, sha256).hexdigest()
    return hmac.compare_digest(header[len(SIGNATURE_PREFIX) :].strip(), expected)


def verification_challenge(
    *, mode: str, token: str, challenge: str, expected_token: str
) -> str:
    """The answer to Meta's setup handshake, or an empty string."""
    if mode != SUBSCRIBE_MODE or not expected_token:
        return ""
    if not hmac.compare_digest(token, expected_token):
        return ""
    return challenge


def leadgen_notices(payload: dict[str, Any]) -> tuple[LeadNotice, ...]:
    """Every lead named in one delivery, in the order Meta listed them."""
    if payload.get("object") != PAGE_OBJECT:
        return ()

    entries = payload.get("entry")
    if not isinstance(entries, list):
        return ()

    notices: list[LeadNotice] = []
    for entry in entries:
        if isinstance(entry, dict):
            notices.extend(_from_entry(entry))
    return tuple(notices)


def _from_entry(entry: dict[str, Any]) -> list[LeadNotice]:
    """The leads named under one page."""
    changes = entry.get("changes")
    if not isinstance(changes, list):
        return []

    found: list[LeadNotice] = []
    for change in changes:
        if not isinstance(change, dict) or change.get("field") != LEADGEN_FIELD:
            continue
        value = change.get("value")
        if not isinstance(value, dict):
            continue
        notice = _from_value(value, fallback_page=str(entry.get("id", "")))
        if notice is not None:
            found.append(notice)
    return found


def _from_value(value: dict[str, Any], *, fallback_page: str) -> LeadNotice | None:
    """One change, or None when it names no lead."""
    leadgen_id = str(value.get("leadgen_id", "")).strip()
    if not leadgen_id:
        return None

    return LeadNotice(
        page_external_id=str(value.get("page_id", "")).strip() or fallback_page,
        leadgen_external_id=leadgen_id,
        form_external_id=str(value.get("form_id", "")).strip(),
        ad_external_id=str(value.get("ad_id", "")).strip(),
        adset_external_id=str(
            value.get("adgroup_id") or value.get("adset_id") or ""
        ).strip(),
        created_at=_moment(value.get("created_time")),
    )


def _moment(raw: Any) -> datetime | None:
    """Meta's unix timestamp as an aware datetime, or None."""
    if not isinstance(raw, int | float) or isinstance(raw, bool):
        return None
    try:
        return datetime.fromtimestamp(float(raw), tz=UTC)
    except (OverflowError, OSError, ValueError):
        return None


__all__ = [
    "LEADGEN_FIELD",
    "SIGNATURE_PREFIX",
    "SUBSCRIBE_MODE",
    "LeadNotice",
    "leadgen_notices",
    "verification_challenge",
    "verify_signature",
]
