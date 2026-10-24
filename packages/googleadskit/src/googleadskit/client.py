"""The one place this package opens a socket, and how Google's answers read.

REST over httpx rather than Google's own client library: one more
dependency for every project that uses this package would buy a gRPC stack
we do not need, and the REST surface is the same API, field for field.

**No developer token.** Since September 2026 the access level belongs to
the Google Cloud project behind the OAuth client, and Google ignores the
header. **``login-customer-id``** is sent only when the account is reached
through a manager account - then Google requires it, otherwise it must be
absent.

**No retry loop**, as in every package here: whether a second attempt is
safe is the caller's knowledge, not this module's.
"""

from collections.abc import Iterator, Mapping
from types import TracebackType
from typing import Any, Final, Self

import httpx

from googleadskit.errors import (
    FailureReason,
    GoogleAdsAPIError,
    GoogleAdsOutcomeUnknown,
    GoogleAdsUnreachable,
)

# The one place the API version is written. Google retires a version about
# a year after it ships; moving it is a change here and a run of the tests.
API_VERSION: Final = "v25"
BASE_URL: Final = f"https://googleads.googleapis.com/{API_VERSION}"

CONNECT_TIMEOUT_SECONDS: Final = 5.0
# A search over a large account is the slowest read this package makes.
READ_TIMEOUT_SECONDS: Final = 60.0

# Failures that happen before a byte of the request reaches Google.
_NOT_SENT: Final = (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout)
_MESSAGE_MAX_CHARS: Final = 300
_FAILURE_TYPE: Final = "GoogleAdsFailure"


class AdsClient:
    """One person's access to Google Ads for the length of a ``with`` block.

    ``token`` is a live access token, not the refresh token. ``http`` is for
    tests and for a caller that wants to share one connection pool; when it
    is lent, this class does not close it.
    """

    def __init__(
        self,
        *,
        token: str,
        login_customer_id: str = "",
        http: httpx.Client | None = None,
    ) -> None:
        self._token = token
        self._login_customer_id = login_customer_id
        self._owned = http is None
        self._http = http or httpx.Client(
            timeout=httpx.Timeout(
                connect=CONNECT_TIMEOUT_SECONDS,
                read=READ_TIMEOUT_SECONDS,
                write=READ_TIMEOUT_SECONDS,
                pool=CONNECT_TIMEOUT_SECONDS,
            )
        )

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        if self._owned:
            self._http.close()

    def __repr__(self) -> str:
        # The token stays out of every repr, as it stays out of every log.
        return f"AdsClient(login_customer_id={self._login_customer_id!r})"

    def get(self, path: str) -> dict[str, Any]:
        return self._call("GET", path)

    def post(self, path: str, body: Mapping[str, Any]) -> dict[str, Any]:
        return self._call("POST", path, body=body)

    def search(self, customer_id: str, query: str) -> Iterator[dict[str, Any]]:
        """Every row a GAQL query returns, page after page.

        ``:search`` rather than ``:searchStream``: a page that fails can be
        asked for again by its token, while a stream that breaks halfway
        has to start over. Each page is one operation against the daily
        quota, so the pages are as large as Google allows.
        """
        page_token = ""
        while True:
            body: dict[str, Any] = {"query": query}
            if page_token:
                body["pageToken"] = page_token
            answer = self.post(f"customers/{customer_id}/googleAds:search", body)
            yield from answer.get("results", [])
            page_token = str(answer.get("nextPageToken") or "")
            if not page_token:
                return

    def _call(
        self, method: str, path: str, *, body: Mapping[str, Any] | None = None
    ) -> dict[str, Any]:
        headers = {"Authorization": f"Bearer {self._token}"}
        if self._login_customer_id:
            headers["login-customer-id"] = self._login_customer_id
        try:
            response = self._http.request(
                method, f"{BASE_URL}/{path}", json=body, headers=headers
            )
        except _NOT_SENT as exc:
            raise GoogleAdsUnreachable(
                f"could not reach Google Ads: {type(exc).__name__}"
            ) from exc
        except httpx.TransportError as exc:
            raise GoogleAdsOutcomeUnknown(
                f"Google Ads did not answer: {type(exc).__name__}"
            ) from exc

        payload = _decode(response)
        if response.status_code >= 400:
            raise _refusal(response.status_code, payload)
        return payload


def _decode(response: httpx.Response) -> dict[str, Any]:
    """The body as a dict. Empty is a normal answer; HTML is a proxy's."""
    if not response.content:
        return {}
    try:
        payload = response.json()
    except ValueError:
        raise GoogleAdsAPIError(
            f"Google Ads answered with something other than JSON "
            f"({response.status_code})",
            http_status=response.status_code,
        ) from None
    return payload if isinstance(payload, dict) else {}


def _refusal(http_status: int, payload: Mapping[str, Any]) -> GoogleAdsAPIError:
    """Google's error envelope, every part of it kept."""
    error = payload.get("error")
    error = error if isinstance(error, dict) else {}
    reasons: list[FailureReason] = []
    request_id = ""
    retry_after = 0
    for detail in error.get("details") or []:
        if not isinstance(detail, dict):
            continue
        if not str(detail.get("@type", "")).endswith(_FAILURE_TYPE):
            continue
        request_id = request_id or str(detail.get("requestId") or "")
        for entry in detail.get("errors") or []:
            code = entry.get("errorCode") if isinstance(entry, dict) else None
            if isinstance(code, dict):
                reasons.extend(FailureReason(str(k), str(v)) for k, v in code.items())
            retry_after = max(retry_after, _retry_delay(entry))
    return GoogleAdsAPIError(
        str(error.get("message") or "Google Ads refused the request")[
            :_MESSAGE_MAX_CHARS
        ],
        http_status=http_status,
        status=str(error.get("status") or ""),
        reasons=tuple(reasons),
        request_id=request_id,
        retry_after_seconds=retry_after,
    )


def _retry_delay(entry: object) -> int:
    """Seconds from a quota error's ``retryDelay`` ("30s"), or nothing."""
    if not isinstance(entry, dict):
        return 0
    details = entry.get("details")
    quota = details.get("quotaErrorDetails") if isinstance(details, dict) else None
    delay = quota.get("retryDelay") if isinstance(quota, dict) else None
    if not isinstance(delay, str) or not delay.endswith("s"):
        return 0
    try:
        return int(float(delay[:-1]))
    except ValueError:
        return 0


__all__ = ["API_VERSION", "BASE_URL", "AdsClient"]
