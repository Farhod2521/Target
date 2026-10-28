"""The two calls this product makes to Multicard: a token, and an invoice.

The only provider here that is *called* rather than only answered: its
checkout page exists once an invoice has been created through its API. The
token is a JWT good for about a day; it is kept in memory and asked for again
shortly before it runs out, or at once when an answer says it was refused.
"""

import logging
import threading
import time
from collections.abc import Mapping
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from paykit.errors import ProviderUnavailable
from paykit.multicard.codes import TOKEN_MARGIN_SECONDS, TOKEN_ZONE

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 15.0


class MulticardClient:
    """A thin, thread-safe HTTP client holding one application's token."""

    def __init__(
        self,
        *,
        base_url: str,
        application_id: str,
        secret: str,
        transport: httpx.BaseTransport | None = None,
        timeout: float = TIMEOUT_SECONDS,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._application_id = application_id
        self._secret = secret
        self._http = httpx.Client(timeout=timeout, transport=transport)
        self._lock = threading.Lock()
        self._token = ""
        self._good_until = 0.0

    def create_invoice(self, payload: Mapping[str, Any]) -> dict[str, Any]:
        """``POST /payment/invoice``; the ``data`` of a successful answer."""
        return self._call("POST", "/payment/invoice", json=dict(payload))

    def invoice(self, uuid: str) -> dict[str, Any]:
        """``GET /payment/invoice/{uuid}``; the invoice as Multicard holds it."""
        return self._call("GET", f"/payment/invoice/{uuid}")

    def _call(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        for attempt in range(2):
            token = self._current_token(fresh=attempt > 0)
            try:
                response = self._http.request(
                    method,
                    self._base_url + path,
                    headers={"Authorization": f"Bearer {token}"},
                    **kwargs,
                )
            except httpx.HTTPError as exc:
                raise ProviderUnavailable(
                    f"multicard {path}: {type(exc).__name__}"
                ) from exc
            if response.status_code == 401 and attempt == 0:
                continue
            return _data(response, path=path)
        raise ProviderUnavailable(f"multicard {path}: token refused twice")

    def _current_token(self, *, fresh: bool) -> str:
        with self._lock:
            if fresh or not self._token or time.time() >= self._good_until:
                self._token, self._good_until = self._authenticate()
            return self._token

    def _authenticate(self) -> tuple[str, float]:
        try:
            response = self._http.post(
                self._base_url + "/auth",
                json={"application_id": self._application_id, "secret": self._secret},
            )
        except httpx.HTTPError as exc:
            raise ProviderUnavailable(f"multicard /auth: {type(exc).__name__}") from exc
        if response.status_code != 200:
            raise ProviderUnavailable(
                f"multicard /auth answered {response.status_code}"
            )
        body = response.json()
        token = str(body.get("token") or "")
        if not token:
            raise ProviderUnavailable("multicard /auth answered without a token")
        return token, _expiry(str(body.get("expiry") or "")) - TOKEN_MARGIN_SECONDS


def _expiry(value: str) -> float:
    """Multicard's ``expiry`` as a timestamp; an hour from now if unreadable."""
    try:
        moment = datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(
            tzinfo=ZoneInfo(TOKEN_ZONE)
        )
    except ValueError:
        return time.time() + 3600
    return moment.timestamp()


def _data(response: httpx.Response, *, path: str) -> dict[str, Any]:
    try:
        body = response.json()
    except ValueError as exc:
        raise ProviderUnavailable(
            f"multicard {path} answered {response.status_code} without JSON"
        ) from exc
    if response.status_code != 200 or not body.get("success"):
        error = body.get("error") or {}
        logger.warning(
            "multicard refused a request",
            extra={
                "path": path,
                "status": response.status_code,
                "code": error.get("code", ""),
                "details": error.get("details", ""),
            },
        )
        raise ProviderUnavailable(
            f"multicard {path}: {error.get('code', response.status_code)}"
        )
    data = body.get("data")
    return data if isinstance(data, dict) else {}


__all__ = ["MulticardClient"]
