"""The reader's language for this request or task, without Django's translation."""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Final

LANGUAGES: Final = ("uz", "ru", "en")
DEFAULT: Final = "ru"
LIST_SEPARATOR: Final = ", "

_current: ContextVar[str] = ContextVar("language", default=DEFAULT)


def get_language() -> str:
    return _current.get()


def activate(language: str) -> None:
    _current.set(language if language in LANGUAGES else DEFAULT)


@contextmanager
def override(language: str) -> Iterator[None]:
    token = _current.set(language if language in LANGUAGES else DEFAULT)
    try:
        yield
    finally:
        _current.reset(token)
