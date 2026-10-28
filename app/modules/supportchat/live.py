"""Live fan-out for support chats, over Redis pub/sub.

The database is the source of truth; this only announces rows that already
committed. Routers publish after the service returns, and a hub that is
down never fails a message: the chat stays readable on reload.

What travels is ids and moments. Each socket draws the row for its own
reader. Four things travel: a new message, a message changed (edited or
taken back), one side having read up to a moment, and one side typing.

One channel per client, keyed by the chat's owner: every client has one
chat, so a socket opened before the first message still hears it.
"""

import asyncio
import json
import logging
import threading
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any, Protocol

from app.common.config import settings
from app.modules.supportchat.constants import WS_GROUP_PREFIX
from app.modules.supportchat.models import SupportMessage

logger = logging.getLogger(__name__)

CLIENT_SOCKET_PATH = "/api/v1/support/ws"

MESSAGE = "thread.message"
CHANGED = "thread.changed"
READ = "thread.read"
TYPING = "thread.typing"


def channel_name(*, owner_id: object) -> str:
    """The pub/sub channel one client's chat sockets share."""
    return f"{WS_GROUP_PREFIX}.{owner_id}"


def message_event(*, message_id: object, nonce: str = "") -> dict[str, str]:
    """A stored message. ``nonce`` is the sender's own tag for the press."""
    return {"type": MESSAGE, "message_id": str(message_id), "nonce": nonce}


def change_event(*, message_id: object) -> dict[str, str]:
    """A message whose words changed, or that was taken back: redraw it."""
    return {"type": CHANGED, "message_id": str(message_id)}


def read_event(*, side: str, at: datetime) -> dict[str, Any]:
    """One side has read everything up to ``at``: the other side's ticks."""
    return {"type": READ, "side": side, "at": int(at.timestamp() * 1000)}


def typing_event(*, side: str) -> dict[str, str]:
    """One side is typing. That side's own sockets do not hear it back."""
    return {"type": TYPING, "side": side}


class Hub(Protocol):
    def publish(self, channel: str, event: dict[str, Any]) -> None: ...
    def listen(self, channel: str) -> Any: ...


class MemoryHub:
    """One process's sockets, for tests and a cache-less setup."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._queues: dict[
            str, set[tuple[asyncio.AbstractEventLoop, asyncio.Queue[str]]]
        ] = {}

    def publish(self, channel: str, event: dict[str, Any]) -> None:
        raw = json.dumps(event)
        with self._lock:
            listeners = list(self._queues.get(channel, ()))
        for loop, queue in listeners:
            loop.call_soon_threadsafe(queue.put_nowait, raw)

    @asynccontextmanager
    async def listen(self, channel: str) -> AsyncIterator[AsyncIterator[str]]:
        queue: asyncio.Queue[str] = asyncio.Queue()
        entry = (asyncio.get_running_loop(), queue)
        with self._lock:
            self._queues.setdefault(channel, set()).add(entry)

        async def frames() -> AsyncIterator[str]:
            while True:
                yield await queue.get()

        try:
            yield frames()
        finally:
            with self._lock:
                self._queues.get(channel, set()).discard(entry)


class RedisHub:
    """Every worker's sockets: a publish reaches whichever process holds them."""

    def __init__(self, url: str) -> None:
        self._url = url
        self._client: Any = None

    def publish(self, channel: str, event: dict[str, Any]) -> None:
        if self._client is None:
            import redis

            self._client = redis.Redis.from_url(
                self._url, socket_connect_timeout=2, socket_timeout=2
            )
        self._client.publish(channel, json.dumps(event))

    @asynccontextmanager
    async def listen(self, channel: str) -> AsyncIterator[AsyncIterator[str]]:
        import redis.asyncio as aredis

        client = aredis.Redis.from_url(self._url)
        pubsub = client.pubsub(ignore_subscribe_messages=True)
        await pubsub.subscribe(channel)

        async def frames() -> AsyncIterator[str]:
            async for item in pubsub.listen():
                data = item.get("data")
                if isinstance(data, bytes):
                    yield data.decode()

        try:
            yield frames()
        finally:
            try:
                await pubsub.unsubscribe(channel)
                await pubsub.aclose()
                await client.aclose()
            except Exception:
                logger.warning("support live channel not closed cleanly")


def _build() -> Hub:
    if settings.cache_backend == "memory":
        return MemoryHub()
    return RedisHub(settings.channels_redis_url)


hub: Hub = _build()


def publish(*, owner_id: object, event: dict[str, Any]) -> None:
    """Best effort on purpose: the row is already committed."""
    try:
        hub.publish(channel_name(owner_id=owner_id), event)
    except Exception:
        logger.warning("support live event not sent", extra={"type": event["type"]})


def broadcast_message(*, message: SupportMessage, nonce: str = "") -> None:
    """Announce a stored message to every socket on its chat."""
    publish(
        owner_id=message.owner_id,
        event=message_event(message_id=message.id, nonce=nonce),
    )


def broadcast_change(*, message: SupportMessage) -> None:
    """Announce an edited or taken-back message, to be drawn again."""
    publish(owner_id=message.owner_id, event=change_event(message_id=message.id))


def broadcast_read(*, owner_id: object, side: str, at: datetime) -> None:
    """One side read the chat up to ``at``."""
    publish(owner_id=owner_id, event=read_event(side=side, at=at))
