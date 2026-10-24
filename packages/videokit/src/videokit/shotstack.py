"""Shotstack: put a file there, ask for a render, read how it went."""

import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any, Final

import httpx

from videokit.errors import VideoAuthError, VideoRejected, VideoTemporaryError
from videokit.models import Environment, RenderState, Source

BASE_URL: Final = "https://api.shotstack.io"
DEFAULT_TIMEOUT_SECONDS: Final = 30.0
UPLOAD_TIMEOUT_SECONDS: Final = 900.0

DOWNLOAD_SECONDS: Final = 240.0
_DOWNLOAD_TIMEOUT: Final = httpx.Timeout(30.0, read=60.0)
_PARTIAL: Final = 206
_RANGE_DONE: Final = 416

_AUTH: Final = frozenset({401, 403})
_BUSY: Final = frozenset({408, 409, 425, 429})
_REASON_CHARS: Final = 300


class Shotstack:
    """One account in one environment."""

    def __init__(
        self,
        *,
        api_key: str,
        environment: Environment,
        http: httpx.Client | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        if not api_key:
            raise VideoAuthError("Shotstack API key is empty")
        self._key = api_key
        self._env = environment
        self._http = http
        self._timeout = timeout

    def upload(self, *, path: Path, filename: str = "") -> str:
        """Send a local file; the source's id comes back."""
        body: dict[str, str] = {"filename": filename or path.name}
        answer = self._call(
            "POST", f"/ingest/{self._env}/upload", json=body, what="upload"
        )
        data = _dict(answer.get("data"))
        attributes = _dict(data.get("attributes"))
        signed = str(attributes.get("url") or "")
        source_id = str(data.get("id") or attributes.get("id") or "")
        if not signed or not source_id:
            raise VideoRejected("Shotstack gave no upload address")
        self._put(signed, path=path)
        return source_id

    def source(self, *, source_id: str) -> Source:
        """Where an uploaded file is, and whether it can be edited yet."""
        answer = self._call(
            "GET", f"/ingest/{self._env}/sources/{source_id}", what="source"
        )
        attributes = _dict(_dict(answer.get("data")).get("attributes"))
        duration = attributes.get("duration")
        return Source(
            id=source_id,
            status=attributes.get("status") or "queued",
            url=str(attributes.get("source") or ""),
            duration=float(duration) if isinstance(duration, int | float) else None,
            created=_when(attributes.get("created")),
            updated=_when(attributes.get("updated")),
        )

    def render(self, *, edit: dict[str, Any]) -> str:
        """Queue one render; its id comes back."""
        answer = self._call(
            "POST", f"/edit/{self._env}/render", json=edit, what="render"
        )
        render_id = str(_dict(answer.get("response")).get("id") or "")
        if not render_id:
            raise VideoRejected("Shotstack accepted the render but named no id")
        return render_id

    def render_state(self, *, render_id: str) -> RenderState:
        """How far a render got. ``url`` is the finished file once ``done``."""
        answer = self._call(
            "GET", f"/edit/{self._env}/render/{render_id}", what="render status"
        )
        response = _dict(answer.get("response"))
        duration, render_ms = response.get("duration"), response.get("renderTime")
        total_ms = response.get("totalRenderTime")
        return RenderState(
            id=render_id,
            status=response.get("status") or "queued",
            url=str(response.get("url") or ""),
            error=str(response.get("error") or "")[:_REASON_CHARS],
            duration=float(duration) if isinstance(duration, int | float) else None,
            render_ms=int(render_ms) if isinstance(render_ms, int | float) else None,
            total_ms=int(total_ms) if isinstance(total_ms, int | float) else None,
            created=_when(response.get("created")),
            updated=_when(response.get("updated")),
        )

    def download(
        self, *, url: str, to: Path, max_seconds: float = DOWNLOAD_SECONDS
    ) -> bool:
        """Bring a finished file to disk, picking up where the last try stopped."""
        have = to.stat().st_size if to.exists() else 0
        headers = {"Range": f"bytes={have}-"} if have else {}
        deadline = time.monotonic() + max_seconds
        try:
            with (
                self._client() as client,
                client.stream(
                    "GET", url, headers=headers, timeout=_DOWNLOAD_TIMEOUT
                ) as reply,
            ):
                if reply.status_code == _RANGE_DONE:
                    return True
                _raise_for(reply, what="download", body="")
                mode = "ab" if reply.status_code == _PARTIAL else "wb"
                with to.open(mode) as out:
                    for chunk in reply.iter_bytes():
                        out.write(chunk)
                        if time.monotonic() > deadline:
                            return False
        except httpx.HTTPError as exc:
            raise VideoTemporaryError(f"download failed: {type(exc).__name__}") from exc
        return True

    def _call(
        self, method: str, path: str, *, what: str, json: Any = None
    ) -> dict[str, Any]:
        headers = {"x-api-key": self._key, "Accept": "application/json"}
        try:
            with self._client() as client:
                reply = client.request(
                    method,
                    f"{BASE_URL}{path}",
                    headers=headers,
                    json=json,
                    timeout=self._timeout,
                )
        except httpx.HTTPError as exc:
            raise VideoTemporaryError(f"{what}: {type(exc).__name__}") from exc
        _raise_for(reply, what=what, body=reply.text)
        try:
            payload = reply.json()
        except ValueError as exc:
            raise VideoTemporaryError(f"{what}: answer was not JSON") from exc
        return _dict(payload)

    def _put(self, url: str, *, path: Path) -> None:
        try:
            with self._client() as client, path.open("rb") as handle:
                reply = client.put(url, content=handle, timeout=UPLOAD_TIMEOUT_SECONDS)
        except OSError as exc:
            raise VideoRejected(f"cannot read {path.name}") from exc
        except httpx.HTTPError as exc:
            raise VideoTemporaryError(f"upload: {type(exc).__name__}") from exc
        _raise_for(reply, what="upload", body=reply.text)

    @contextmanager
    def _client(self) -> Iterator[httpx.Client]:
        if self._http is not None:
            yield self._http
            return
        with httpx.Client(follow_redirects=True) as client:
            yield client


_S3_BUSY: Final = ("<Code>RequestTimeout</Code>", "<Code>SlowDown</Code>")


def _raise_for(reply: httpx.Response, *, what: str, body: str) -> None:
    status = reply.status_code
    if status < 400:
        return
    reason = f"{what}: HTTP {status} {body[:_REASON_CHARS]}".strip()
    if status in _AUTH:
        raise VideoAuthError(reason)
    if status in _BUSY or status >= 500 or any(code in body for code in _S3_BUSY):
        raise VideoTemporaryError(reason)
    raise VideoRejected(reason)


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _when(value: Any) -> datetime | None:
    """An ISO moment from the provider (``...T06:29:58.287Z``), if it is one."""
    if not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None
