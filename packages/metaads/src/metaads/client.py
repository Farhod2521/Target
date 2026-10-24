"""Graph API transport: the single source of truth for how we call Meta."""

import json
import time
from collections.abc import Mapping
from types import TracebackType
from typing import Any, Final, Self

import httpx

from metaads import tracing
from metaads.errors import (
    AUTH_CODES,
    RATE_LIMIT_CODES,
    TRANSIENT_CODES,
    MetaAPIError,
    MetaAuthError,
    MetaPayloadTooLarge,
    MetaTemporaryError,
    PagesExhausted,
    RateLimitApproaching,
    describe,
    user_words,
)

API_VERSION: Final = "v26.0"
GRAPH_BASE_URL: Final = f"https://graph.facebook.com/{API_VERSION}"

OAUTH_DIALOG_URL: Final = f"https://www.facebook.com/{API_VERSION}/dialog/oauth"

CONNECT_TIMEOUT_SECONDS: Final = 5.0
READ_TIMEOUT_SECONDS: Final = 30.0

UPLOAD_TIMEOUT_SECONDS: Final = 180.0

USAGE_HEADER: Final = "X-Business-Use-Case-Usage"
APP_USAGE_HEADER: Final = "X-App-Usage"
USAGE_STOP_PERCENT: Final = 80

MAX_PAGES: Final = 25

API_LOCALE: Final = "en_US"

OWN_LOCALE_EDGES: Final = frozenset({"leadgen_forms"})


def _creates_own_locale(method: str, path: str) -> bool:
    """Whether this request creates an object whose ``locale`` is a field."""
    edge = path.rstrip("/").rsplit("/", 1)[-1]
    return method == "POST" and edge in OWN_LOCALE_EDGES


class GraphClient:
    """One conversation with the Graph API."""

    def __init__(
        self,
        *,
        token: str = "",
        base_url: str = GRAPH_BASE_URL,
        client: httpx.Client | None = None,
    ) -> None:
        self._token = token
        self._base_url = base_url.rstrip("/")
        self._client = client or httpx.Client(
            timeout=httpx.Timeout(
                connect=CONNECT_TIMEOUT_SECONDS,
                read=READ_TIMEOUT_SECONDS,
                write=READ_TIMEOUT_SECONDS,
                pool=CONNECT_TIMEOUT_SECONDS,
            )
        )
        self._owns_client = client is None
        self._brake = _Brake()

    def for_token(self, token: str) -> "GraphClient":
        """The same connection pool, speaking as somebody else."""
        if token == self._token:
            return self
        clone = GraphClient(token=token, base_url=self._base_url, client=self._client)
        clone._brake = self._brake
        return clone

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        """Only closes what it opened. A borrowed client stays open."""
        if self._owns_client:
            self._client.close()

    def get(self, path: str, **params: Any) -> dict[str, Any]:
        return self._request("GET", path, params=self._with_token(params))

    def post(self, path: str, **data: Any) -> dict[str, Any]:
        return self._request("POST", path, data=self._with_token(data))

    def delete(self, path: str, **params: Any) -> dict[str, Any]:
        """Remove one object. The rollback's only verb."""
        return self._request("DELETE", path, params=self._with_token(params))

    def delete_body(self, path: str, **data: Any) -> dict[str, Any]:
        """A DELETE whose subject is a body rather than a path."""
        return self._request("DELETE", path, params=self._with_token({}), data=data)

    def upload(
        self, path: str, *, files: dict[str, Any], **data: Any
    ) -> dict[str, Any]:
        """A multipart POST, for the one thing Meta will not take as a field."""
        return self._request(
            "POST",
            path,
            data=self._with_token(data),
            files=files,
            timeout=UPLOAD_TIMEOUT_SECONDS,
        )

    def get_all(
        self, path: str, *, max_pages: int = MAX_PAGES, **params: Any
    ) -> list[dict[str, Any]]:
        """Follow cursor paging and return every row, or refuse to guess."""
        rows: list[dict[str, Any]] = []
        payload = self.get(path, **params)

        for page in range(1, max_pages + 1):
            rows.extend(payload.get("data", []))
            following = payload.get("paging", {}).get("next")
            if not following:
                return rows
            if page == max_pages:
                raise PagesExhausted(
                    f"{path} still had pages after {max_pages}",
                    rows=rows,
                    pages=page,
                )
            payload = self._request("GET", following)

        return rows

    def _with_token(self, values: dict[str, Any]) -> dict[str, Any]:
        """Token in the query, which is what Meta's own examples use."""
        return {**values, "access_token": self._token} if self._token else values

    def _request(
        self,
        method: str,
        path_or_url: str,
        *,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        files: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        following = path_or_url.startswith("http")
        url = (
            path_or_url if following else f"{self._base_url}/{path_or_url.lstrip('/')}"
        )

        pinned = not following and not _creates_own_locale(method, path_or_url)
        query = {**(params or {}), "locale": API_LOCALE} if pinned else params

        extra: dict[str, Any] = {"timeout": timeout} if timeout is not None else {}

        self._brake.check()

        started = time.perf_counter()
        try:
            response = self._client.request(
                method, url, params=query, data=data, files=files, **extra
            )
        except httpx.TimeoutException as exc:
            self._watched(method, url, query, data, started, error=str(exc))
            raise MetaTemporaryError(f"Meta did not answer in time: {exc}") from exc
        except httpx.TransportError as exc:
            self._watched(method, url, query, data, started, error=str(exc))
            raise MetaTemporaryError(f"could not reach Meta: {exc}") from exc

        self._watched(method, url, query, data, started, response=response)

        self._brake_on(response)

        if response.status_code >= 400:
            raise self._translate(response)

        payload = self._decode(response)

        if isinstance(payload.get("error"), Mapping):
            raise self._translate(response)

        return payload

    @staticmethod
    def _watched(
        method: str,
        url: str,
        query: dict[str, Any] | None,
        body: dict[str, Any] | None,
        started: float,
        *,
        response: httpx.Response | None = None,
        error: str = "",
    ) -> None:
        """Hand one attempt to whoever is watching. Costs nothing when
        nobody is - ``report`` returns on a missing watcher before touching
        anything, and it never raises."""
        if tracing.current() is None:
            return

        payload: Any = None
        if response is not None:
            try:
                payload = response.json()
            except ValueError:
                payload = response.text[:2000]

        tracing.report(
            method=method,
            url=url,
            query=query,
            body=body,
            status=response.status_code if response is not None else 0,
            response=payload,
            ms=(time.perf_counter() - started) * 1000,
            error=error,
        )

    @staticmethod
    def _decode(response: httpx.Response) -> dict[str, Any]:
        try:
            payload = response.json()
        except ValueError as exc:
            raise MetaAPIError(
                f"Meta returned a non-JSON body ({response.status_code})"
            ) from exc

        if not isinstance(payload, dict):
            return {"result": payload}
        return payload

    @staticmethod
    def _translate(response: httpx.Response) -> MetaAPIError:
        """Turn one Meta error body into the right class to raise."""
        try:
            error = response.json().get("error", {})
        except ValueError:
            error = {}

        code = error.get("code")
        subcode = error.get("error_subcode")
        title, sentence = user_words(error)
        message = describe(error, fallback=f"HTTP {response.status_code}")

        if response.status_code == httpx.codes.REQUEST_ENTITY_TOO_LARGE:
            return MetaPayloadTooLarge(message, code=code, subcode=subcode)
        if code in AUTH_CODES:
            return MetaAuthError(
                message,
                code=code,
                subcode=subcode,
                user_title=title,
                user_message=sentence,
            )
        if code in TRANSIENT_CODES:
            return MetaTemporaryError(
                message,
                code=code,
                subcode=subcode,
                user_title=title,
                user_message=sentence,
            )
        if code in RATE_LIMIT_CODES:
            return RateLimitApproaching(
                message,
                code=code,
                subcode=subcode,
                user_title=title,
                user_message=sentence,
            )
        if error.get("is_transient") is True or response.status_code >= 500:
            return MetaTemporaryError(
                message,
                code=code,
                subcode=subcode,
                user_title=title,
                user_message=sentence,
            )
        return MetaAPIError(
            message,
            code=code,
            subcode=subcode,
            user_title=title,
            user_message=sentence,
        )

    def _brake_on(self, response: httpx.Response) -> None:
        """Set the brake when this answer says the budget is nearly gone."""
        try:
            self._check_usage(response)
        except RateLimitApproaching as stop:
            self._brake.stop = stop

    @staticmethod
    def _check_usage(response: httpx.Response) -> None:
        """Stop at 80 percent of a call budget rather than at 100."""
        worst = max(
            _worst_business_usage(response.headers.get(USAGE_HEADER)),
            _worst_app_usage(response.headers.get(APP_USAGE_HEADER)),
        )
        if worst >= USAGE_STOP_PERCENT:
            raise RateLimitApproaching(
                f"Meta usage at {worst:.0f} percent", percent=worst
            )


class _Brake:
    """A stop one answer asked for, held for the next call to meet."""

    __slots__ = ("stop",)

    def __init__(self) -> None:
        self.stop: RateLimitApproaching | None = None

    def check(self) -> None:
        if self.stop is not None:
            raise RateLimitApproaching(str(self.stop), percent=self.stop.percent)


USAGE_FIGURES: Final = ("call_count", "total_cputime", "total_time")


def _worst_app_usage(raw: str | None) -> float:
    """The app-wide budget: one flat object, one deployment, every customer."""
    usage = _parsed(raw)
    if not isinstance(usage, dict):
        return 0.0
    return max((_number(usage.get(name)) for name in USAGE_FIGURES), default=0.0)


def _worst_business_usage(raw: str | None) -> float:
    """The per-account budget: an object keyed by id, holding lists."""
    usage = _parsed(raw)
    if not isinstance(usage, dict):
        return 0.0
    return max(
        (
            _number(entry.get(name))
            for entries in usage.values()
            if isinstance(entries, list)
            for entry in entries
            if isinstance(entry, dict)
            for name in USAGE_FIGURES
        ),
        default=0.0,
    )


def _parsed(raw: str | None) -> Any:
    """The header as JSON, or ``None``. A malformed header is not our bug."""
    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return None


def _number(value: Any) -> float:
    """One figure as a float. Meta has sent strings here before now."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
