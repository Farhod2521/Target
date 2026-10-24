"""In-process hooks, so one module can react to another without importing it."""

from collections import defaultdict
from collections.abc import Callable
from typing import Any

_handlers: dict[str, list[Callable[..., Any]]] = defaultdict(list)


def on(name: str) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    def register(fn: Callable[..., Any]) -> Callable[..., Any]:
        _handlers[name].append(fn)
        return fn

    return register


def fire(name: str, **kwargs: Any) -> None:
    for fn in _handlers[name]:
        fn(**kwargs)
