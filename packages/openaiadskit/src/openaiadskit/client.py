"""The one place this package opens a socket, and how OpenAI's answers read.

**The API key is the whole credential.** OpenAI scopes each Ads API key to
one ad account, so there is no account id on any path: the key says which
account every call is about.

**Lists are cursor-paged** (``limit``, ``after``, ``has_more``,
``last_id``); :meth:`AdsClient.pages` walks them to the end.

**No retry loop**, as in every package here: whether a second attempt is
safe is the caller's knowledge, not this module's. Creates take an
``Idempotency-Key`` so that a caller who does retry cannot make two.
"""

from collections.abc import Iterator, Mapping, Sequence
from types import TracebackType
from typing import Any, Final, Self

import httpx

from openaiadskit.errors import (
    OpenAIAdsAPIError,
    OpenAIAdsOutcomeUnknown,
    OpenAIAdsUnreachable,
)

# The one place the API version is written.
API_VERSION: Final = "v1"
BASE_URL: Final = f"https://api.ads.openai.com/{API_VERSION}"

CONNECT_TIMEOUT_SECONDS: Final = 5.0
READ_TIMEOUT_SECONDS: Final = 60.0
# An image upload carries the file itself.
UPLOAD_TIMEOUT_SECONDS: Final = 120.0
# The largest page every list endpoint accepts.
PAGE_SIZE: Final = 500

_NOT_SENT: Final = (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout)
_MESSAGE_MAX_CHARS: Final = 300

Params = Mapping[str, str | int | Sequence[str]]


class AdsClient:
    """One ad account's API key for the length of a ``with`` block.

    ``http`` is for tests and for a caller that wants to share one
    connection pool; when it is lent, this class does not close it.
    """

    def __init__(self, *, api_key: str, http: httpx.Client | None = None) -> None:
        self._api_key = api_key
        self._owned = http is None
        self._http = http or httpx.Client(
            timeout=httpx.Timeout(
                connect=CONNECT_TIMEOUT_SECONDS,
                read=READ_TIMEOUT_SECONDS,
                write=UPLOAD_TIMEOUT_SECONDS,
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
        # The key stays out of every repr, as it stays out of every log.
        return "AdsClient()"

    def get(self, path: str, params: Params | None = None) -> dict[str, Any]:
        return self._call("GET", path, params=params)

    def post(
        self,
        path: str,
        body: Mapping[str, Any] | None = None,
        *,
        idempotency_key: str = "",
    ) -> dict[str, Any]:
        headers = {"Idempotency-Key": idempotency_key} if idempotency_key else {}
        return self._call("POST", path, body=body or {}, headers=headers)

    def upload(
        self, *, content: bytes, filename: str, content_type: str
    ) -> dict[str, Any]:
        """``POST /upload`` with the image itself, as multipart."""
        return self._call(
            "POST", "upload", files={"file": (filename, content, content_type)}
        )

    def pages(
        self, path: str, params: Params | None = None
    ) -> Iterator[dict[str, Any]]:
        """Every item a list endpoint returns, page after page."""
        after = ""
        while True:
            query: dict[str, Any] = dict(params or {})
            query["limit"] = query.get("limit", PAGE_SIZE)
            if after:
                query["after"] = after
            answer = self.get(path, query)
            data = answer.get("data")
            yield from (row for row in data or [] if isinstance(row, dict))
            after = str(answer.get("last_id") or "")
            if not answer.get("has_more") or not after:
                return

    def _call(
        self,
        method: str,
        path: str,
        *,
        params: Params | None = None,
        body: Mapping[str, Any] | None = None,
        files: Mapping[str, tuple[str, bytes, str]] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        sent = {
            "Authorization": f"Bearer {self._api_key}",
            "Accept": "application/json",
        }
        sent.update(headers or {})
        try:
            response = self._http.request(
                method,
                f"{BASE_URL}/{path}",
                params=_query(params),
                json=body if files is None else None,
                files=files,
                headers=sent,
            )
        except _NOT_SENT as exc:
            raise OpenAIAdsUnreachable(
                f"could not reach ChatGPT Ads: {type(exc).__name__}"
            ) from exc
        except httpx.TransportError as exc:
            raise OpenAIAdsOutcomeUnknown(
                f"ChatGPT Ads did not answer: {type(exc).__name__}"
            ) from exc

        payload = _decode(response)
        if response.status_code >= 400:
            raise _refusal(response, payload)
        return payload


def _query(params: Params | None) -> list[tuple[str, str | int | float | bool | None]]:
    """Lists as OpenAI spells them: ``fields[]=a&fields[]=b``."""
    pairs: list[tuple[str, str | int | float | bool | None]] = []
    for key, value in (params or {}).items():
        if isinstance(value, str | int):
            pairs.append((key, str(value)))
        else:
            pairs.extend((f"{key}[]", str(item)) for item in value)
    return pairs


def _decode(response: httpx.Response) -> dict[str, Any]:
    """The body as a dict. Empty is a normal answer; HTML is a proxy's."""
    if not response.content:
        return {}
    try:
        payload = response.json()
    except ValueError:
        raise OpenAIAdsAPIError(
            f"ChatGPT Ads answered with something other than JSON "
            f"({response.status_code})",
            http_status=response.status_code,
        ) from None
    return payload if isinstance(payload, dict) else {}


def _refusal(response: httpx.Response, payload: Mapping[str, Any]) -> OpenAIAdsAPIError:
    error = payload.get("error")
    error = error if isinstance(error, dict) else {}
    message = error.get("message") or payload.get("message") or payload.get("detail")
    return OpenAIAdsAPIError(
        str(message or "ChatGPT Ads refused the request")[:_MESSAGE_MAX_CHARS],
        http_status=response.status_code,
        type=str(error.get("type") or ""),
        code=str(error.get("code") or ""),
        param=str(error.get("param") or ""),
        request_id=str(response.headers.get("x-request-id") or ""),
        retry_after_seconds=_retry_after(response.headers.get("retry-after")),
    )


def _retry_after(value: str | None) -> int:
    try:
        return max(0, int(float(value or 0)))
    except ValueError:
        return 0


__all__ = ["API_VERSION", "BASE_URL", "AdsClient"]
