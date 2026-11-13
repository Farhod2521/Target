"""UTeL's REST API, the three things the settings need: a key for a login,
the internal numbers, and the list of addresses it sends events to.

Answers come as ``{"status", "code", "result", "message"}``; the call
history and the internal numbers are paged, as ``{"data", "links", "meta"}``.
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final

import httpx

from app.modules.telephony.constants import HOOK_EVENTS, UTEL_ZONE

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS: Final = 15.0
_NO_ENTRY: Final = frozenset({401, 403})
_BAD_INPUT: Final = frozenset({400, 422})


class Refused(Exception):
    """The exchange said no to the login or the key."""


class Unreachable(Exception):
    """No answer, or one that is not UTeL's."""


class NotTaken(Unreachable):
    """The exchange read what we sent and would not take it."""


@dataclass(frozen=True, slots=True)
class Extension:
    number: str
    title: str
    password: str


def api_base(tenant: str) -> str:
    return f"https://api.{tenant}.{UTEL_ZONE}/api/v1"


def _send(
    method: str,
    tenant: str,
    path: str,
    *,
    token: str = "",
    body: Any = None,
    params: dict[str, Any] | None = None,
) -> dict[str, Any]:
    headers = {"Accept": "application/json", "Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        answer = httpx.request(
            method,
            f"{api_base(tenant)}{path}",
            headers=headers,
            json=body,
            params=params,
            timeout=TIMEOUT_SECONDS,
            follow_redirects=False,
        )
    except httpx.HTTPError as exc:
        logger.warning("utel %s %s: %s", method, path, type(exc).__name__)
        raise Unreachable from exc
    if answer.status_code in _NO_ENTRY:
        raise Refused
    if answer.status_code in _BAD_INPUT:
        logger.warning(
            "utel %s %s would not take it: %s", method, path, answer.status_code
        )
        raise NotTaken
    if answer.status_code != httpx.codes.OK:
        logger.warning("utel %s %s answered %s", method, path, answer.status_code)
        raise Unreachable
    try:
        found = answer.json()
    except ValueError as exc:
        raise Unreachable from exc
    if not isinstance(found, dict):
        raise Unreachable
    return found


def _call(
    method: str,
    tenant: str,
    path: str,
    *,
    token: str = "",
    body: Any = None,
) -> Any:
    found = _send(method, tenant, path, token=token, body=body)
    if "result" not in found:
        raise Unreachable
    return found["result"]


def login(tenant: str, *, email: str, password: str) -> str:
    """The key for this login. It does not run out by itself."""
    try:
        result = _call(
            "POST", tenant, "/auth/login", body={"email": email, "password": password}
        )
    except NotTaken as exc:
        # A wrong password is not shown in UTeL's pages; a login it will
        # not take is a refusal whichever of the two codes it answers.
        raise Refused from exc
    token = result.get("access_token") if isinstance(result, dict) else None
    if not isinstance(token, str) or not token:
        raise Unreachable
    return token


EXTENSION_PAGES_MAX: Final = 20


def _extension_rows(tenant: str, *, token: str) -> list[Any]:
    """The real exchange answers this one as the paged ``{"data", "meta"}``
    and not in the ``result`` envelope its guide shows; both are read."""
    rows: list[Any] = []
    for page in range(1, EXTENSION_PAGES_MAX + 1):
        found = _send(
            "GET",
            tenant,
            "/ats/ps-user",
            token=token,
            params={"page": page} if page > 1 else None,
        )
        listed = found.get("result")
        if not isinstance(listed, list):
            listed = found.get("data")
        if not isinstance(listed, list):
            raise Unreachable
        rows += listed
        meta = found.get("meta")
        last = meta.get("last_page") if isinstance(meta, dict) else None
        if not isinstance(last, int) or page >= last or not listed:
            break
    return rows


def extensions(tenant: str, *, token: str) -> list[Extension]:
    found = []
    for row in _extension_rows(tenant, token=token):
        if not isinstance(row, dict):
            continue
        number = str(row.get("username") or "").strip()
        if not number:
            continue
        found.append(
            Extension(
                number=number,
                title=str(row.get("title") or "").strip(),
                password=str(row.get("password") or ""),
            )
        )
    return found


def hooks(tenant: str, *, token: str) -> list[dict[str, Any]]:
    result = _call("GET", tenant, "/integration/webhook", token=token)
    if not isinstance(result, list):
        raise Unreachable
    return [row for row in result if isinstance(row, dict)]


def put_hooks(tenant: str, *, token: str, rows: list[dict[str, Any]]) -> None:
    """Replaces the whole list: what is not sent is deleted there."""
    _call("PUT", tenant, "/integration/webhook", token=token, body=rows)


def hook_row(url: str) -> dict[str, Any]:
    return {"url": url} | dict.fromkeys(HOOK_EVENTS, True)


HISTORY_PAGE: Final = 300
HISTORY_TIME: Final = "%Y-%m-%d %H:%M:%S"


def call_history(
    tenant: str, *, token: str, start: datetime, end: datetime, page: int
) -> tuple[list[dict[str, Any]], int]:
    """One page of finished calls between two moments on the exchange's own
    clock, newest first, and the number of the last page."""
    found = _send(
        "GET",
        tenant,
        "/call-history",
        token=token,
        params={
            "per_page": HISTORY_PAGE,
            "page": page,
            "sort": "-id",
            "filter[from]": start.strftime(HISTORY_TIME),
            "filter[to]": end.strftime(HISTORY_TIME),
        },
    )
    rows = found.get("data")
    if not isinstance(rows, list):
        raise Unreachable
    meta = found.get("meta")
    last = meta.get("last_page") if isinstance(meta, dict) else None
    return (
        [row for row in rows if isinstance(row, dict)],
        last if isinstance(last, int) and last > 0 else 1,
    )
