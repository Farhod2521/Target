"""An optional pair of eyes on every Graph call.

Exists for one job: a diagnostic run where somebody needs to see what was
sent and what came back, in order, for one sequence of calls. Nothing in
the package depends on it and nothing changes when it is off, which is the
only way a hook like this is worth having - a tracer that alters behaviour
is a tracer that hides the bug it was turned on for.

A :class:`~contextvars.ContextVar` rather than a module global: the worker
runs several launches at once and a global would file one launch's calls
under another's. Contextvars follow the task, which is exactly the scope a
"this sequence of calls" watcher wants.

The package redacts its own secret before handing anything over. It knows
where it put the token - it wrote the parameter - and a caller that has to
remember to strip it is a caller that eventually forgets.
"""

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Final, Protocol

# Query and body keys never handed to a watcher. The first is ours; the
# rest are here because Meta echoes some inputs back and a page token in a
# response body is the same secret as one in a request.
SECRET_KEYS: Final[frozenset[str]] = frozenset(
    {
        "access_token",
        "app_secret",
        "client_secret",
        "code",
        "fb_exchange_token",
        "input_token",
        "page_token",
        "token",
    }
)
MASK: Final = "***"


class Watcher(Protocol):
    """What a tracer has to accept. Called once per finished attempt."""

    def __call__(
        self,
        *,
        method: str,
        url: str,
        query: Mapping[str, Any],
        body: Mapping[str, Any],
        status: int,
        response: Any,
        ms: float,
        error: str = "",
    ) -> None: ...


_watcher: ContextVar[Watcher | None] = ContextVar("metaads_watcher", default=None)


@contextmanager
def watching(watcher: Watcher) -> Iterator[None]:
    """Watch every call made inside this block, then stop."""
    token = _watcher.set(watcher)
    try:
        yield
    finally:
        _watcher.reset(token)


def current() -> Watcher | None:
    """The watcher for this context, or ``None`` when nobody is looking."""
    return _watcher.get()


def scrubbed(values: Mapping[str, Any] | None) -> dict[str, Any]:
    """The same mapping with anything secret replaced by a mask.

    Key-based rather than value-based on purpose. A token is recognisable
    by where it sits, not by what it looks like, and a check that hunts for
    ``EAA`` prefixes fails the first time Meta changes the format.
    """
    if not values:
        return {}
    return {
        key: (MASK if key.lower() in SECRET_KEYS else value)
        for key, value in values.items()
    }


def report(
    *,
    method: str,
    url: str,
    query: Mapping[str, Any] | None,
    body: Mapping[str, Any] | None,
    status: int,
    response: Any = None,
    ms: float,
    error: str = "",
) -> None:
    """Hand one finished attempt to the watcher, if there is one.

    Never raises. A tracer that breaks the call it was observing turns a
    diagnostic aid into an outage, and the thing being diagnosed is usually
    already fragile.
    """
    watcher = current()
    if watcher is None:
        return
    try:
        watcher(
            method=method,
            url=_bare(url),
            query=scrubbed(query),
            body=scrubbed(body),
            status=status,
            response=response,
            ms=ms,
            error=error,
        )
    except Exception:
        return


def _bare(url: str) -> str:
    """A URL with its query string removed.

    Paging cursors are absolute and carry the access token inside them, so
    the string itself is a secret. The path is the part worth reading.
    """
    return url.split("?", 1)[0]


__all__ = [
    "MASK",
    "SECRET_KEYS",
    "Watcher",
    "current",
    "report",
    "scrubbed",
    "watching",
]
