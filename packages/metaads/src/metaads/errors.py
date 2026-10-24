"""Graph API failures, split by what the caller should do about them."""

import json
import re
from collections.abc import Mapping
from typing import Any

TRANSIENT_CODES = frozenset({1, 2})
BUSINESS_USE_CASE_CODES = frozenset(range(80000, 80015))
TEMPORARY_BLOCK_CODES = frozenset({368})
RATE_LIMIT_CODES = (
    frozenset({4, 17, 32, 613}) | BUSINESS_USE_CASE_CODES | TEMPORARY_BLOCK_CODES
)
RETRYABLE_CODES = TRANSIENT_CODES | RATE_LIMIT_CODES

AUTH_CODES = frozenset({31, 190, 200, 294})


class MetaError(Exception):
    """Base for anything that went wrong while talking to Meta."""


class MetaAPIError(MetaError):
    """Meta answered with an error body. Permanent unless stated otherwise."""

    def __init__(
        self,
        message: str,
        *,
        code: int | None = None,
        subcode: int | None = None,
        user_title: str = "",
        user_message: str = "",
    ) -> None:
        super().__init__(message)
        self.code = code
        self.subcode = subcode
        self.user_title = user_title
        self.user_message = user_message


class MetaTemporaryError(MetaAPIError):
    """Transient: 5xx, timeout, a code in ``TRANSIENT_CODES``, or a body
    Meta marked ``is_transient`` that is not a rate limit."""


class MetaPayloadTooLarge(MetaAPIError):
    """HTTP 413: the request body was bigger than Meta takes in one request."""


class RateLimitApproaching(MetaTemporaryError):
    """Usage crossed the stop threshold, or Meta reported a rate limit."""

    def __init__(
        self,
        message: str = "Meta rate limit threshold reached",
        *,
        percent: float | None = None,
        retry_after: int | None = None,
        code: int | None = None,
        subcode: int | None = None,
        user_title: str = "",
        user_message: str = "",
    ) -> None:
        super().__init__(
            message,
            code=code,
            subcode=subcode,
            user_title=user_title,
            user_message=user_message,
        )
        self.percent = percent
        self.retry_after = retry_after


class MetaAuthError(MetaAPIError):
    """Token expired, revoked, or missing a permission. Needs a human."""


class PagesExhausted(MetaError):
    """A cursor loop hit its ceiling while Meta still had pages to give."""

    def __init__(
        self,
        message: str,
        *,
        rows: list[Any] | None = None,
        pages: int = 0,
    ) -> None:
        super().__init__(message)
        self.rows = rows or []
        self.pages = pages


def describe(error: Mapping[str, Any], *, fallback: str) -> str:
    """Everything Meta said about one failure, as a single line for the log."""
    parts = [str(error.get("message") or "").strip() or fallback]

    for key in ("error_user_title", "error_user_msg"):
        value = str(error.get(key) or "").strip()
        if value and value not in parts:
            parts.append(value)

    blamed = _blamed(error)
    if blamed:
        parts.append(f"blamed: {blamed}")

    numbers = _numbers(error)
    if numbers:
        parts.append(numbers)

    return " | ".join(parts)


_RETIRED_ARRAY = re.compile(r"\[\s*\{.*}\s*]", re.DOTALL)


def retired_pairs(message: str) -> list[dict[str, str]]:
    """Every withdrawn option named in one refusal, with its replacement."""
    found = _RETIRED_ARRAY.search(message or "")
    if found is None:
        return []

    try:
        rows = json.loads(found.group(0))
    except ValueError:
        return []
    if not isinstance(rows, list):
        return []

    pairs: list[dict[str, str]] = []
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        retired = str(row.get("deprecated_interest_id") or "").strip()
        if not retired:
            continue
        pairs.append(
            {
                "retired_id": retired,
                "retired_name": str(row.get("deprecated_interest_name") or "").strip(),
                "alternative_id": str(row.get("alternative_interest_id") or "").strip(),
                "alternative_name": str(
                    row.get("alternative_interest_name") or ""
                ).strip(),
            }
        )
    return pairs


def _numbers(error: Mapping[str, Any]) -> str:
    """``code 100/1815227`` - the language-independent half of a refusal."""
    code = error.get("code")
    if code is None:
        return ""
    subcode = error.get("error_subcode")
    return f"code {code}" + (f"/{subcode}" if subcode else "")


def _blamed(error: Mapping[str, Any]) -> str:
    """The field names Meta refused, when it named any."""
    data: Any = error.get("error_data")
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except ValueError:
            return ""

    if not isinstance(data, Mapping):
        return ""

    specs = data.get("blame_field_specs")
    if not isinstance(specs, list):
        return ""

    names: list[str] = []
    for group in specs:
        entries = group if isinstance(group, list) else [group]
        names.extend(str(entry).strip() for entry in entries)

    return ", ".join(name for name in names if name)


def user_words(error: Mapping[str, Any]) -> tuple[str, str]:
    """The pair Meta wrote for the advertiser: a title and a sentence."""
    return (
        str(error.get("error_user_title") or "").strip(),
        str(error.get("error_user_msg") or "").strip(),
    )
