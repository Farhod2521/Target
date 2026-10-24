"""A small key-value cache on Redis, with an in-process stand-in for tests."""

import json
import time
from collections.abc import Iterable
from typing import Any, Protocol

from app.common.config import settings


class Cache(Protocol):
    def get(self, key: str, default: Any = None) -> Any: ...
    def get_many(self, keys: Iterable[str]) -> dict[str, Any]: ...
    def set(self, key: str, value: Any, timeout: int | None = None) -> None: ...
    def add(self, key: str, value: Any, timeout: int | None = None) -> bool: ...
    def incr(self, key: str, amount: int = 1) -> int: ...
    def delete(self, key: str) -> None: ...
    def publish(self, channel: str, message: str) -> None: ...


class MemoryCache:
    def __init__(self) -> None:
        self._data: dict[str, tuple[Any, float | None]] = {}

    def _live(self, key: str) -> tuple[Any, float | None] | None:
        found = self._data.get(key)
        if found is None:
            return None
        if found[1] is not None and found[1] < time.monotonic():
            self._data.pop(key, None)
            return None
        return found

    def get(self, key: str, default: Any = None) -> Any:
        found = self._live(key)
        return default if found is None else found[0]

    def get_many(self, keys: Iterable[str]) -> dict[str, Any]:
        return {k: v for k in keys if (v := self.get(k)) is not None}

    def set(self, key: str, value: Any, timeout: int | None = None) -> None:
        expires = time.monotonic() + timeout if timeout else None
        self._data[key] = (value, expires)

    def add(self, key: str, value: Any, timeout: int | None = None) -> bool:
        if self._live(key) is not None:
            return False
        self.set(key, value, timeout)
        return True

    def incr(self, key: str, amount: int = 1) -> int:
        found = self._live(key)
        if found is None:
            raise ValueError(f"key {key!r} not found")
        value = int(found[0]) + amount
        self._data[key] = (value, found[1])
        return value

    def delete(self, key: str) -> None:
        self._data.pop(key, None)

    def clear(self) -> None:
        self._data.clear()

    def publish(self, channel: str, message: str) -> None:
        """Nobody listens in-process; a published nudge goes nowhere."""


class RedisCache:
    def __init__(self, url: str) -> None:
        import redis

        self._redis = redis.Redis.from_url(url)

    def get(self, key: str, default: Any = None) -> Any:
        raw = self._redis.get(key)
        return default if raw is None else json.loads(raw)

    def get_many(self, keys: Iterable[str]) -> dict[str, Any]:
        names = list(keys)
        if not names:
            return {}
        values = self._redis.mget(names)
        return {k: json.loads(v) for k, v in zip(names, values, strict=True) if v}

    def set(self, key: str, value: Any, timeout: int | None = None) -> None:
        self._redis.set(key, json.dumps(value, default=str), ex=timeout or None)

    def add(self, key: str, value: Any, timeout: int | None = None) -> bool:
        return bool(
            self._redis.set(
                key, json.dumps(value, default=str), ex=timeout or None, nx=True
            )
        )

    def incr(self, key: str, amount: int = 1) -> int:
        if not self._redis.exists(key):
            raise ValueError(f"key {key!r} not found")
        return int(self._redis.incrby(key, amount))

    def delete(self, key: str) -> None:
        self._redis.delete(key)

    def publish(self, channel: str, message: str) -> None:
        self._redis.publish(channel, message)


def _build() -> Cache:
    if settings.cache_backend == "memory":
        return MemoryCache()
    return RedisCache(settings.redis_url)


cache: Cache = _build()
